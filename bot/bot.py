from telegram.ext import JobQueue, ChatMemberHandler, ApplicationBuilder,\
                         ContextTypes, CommandHandler, MessageHandler, filters,\
                         CallbackContext, CallbackQueryHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
import database as db
from pony import orm
import datetime
import logging
import messages
import config
import re


logging.basicConfig(level=logging.INFO, filename=config.log_path+'bot.log', filemode='w',
                    format=config.logging_format
)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
botLogger = logging.getLogger(__name__)


class User_list():
    _times_queue = None#include all users's times
    _users = dict()
    _callback = None#function will execute in time for sending a set to user

    def __init__(self, queue: JobQueue, callback_func):
        self._times_queue = queue
        self._callback = callback_func
        with orm.db_session:
            for user_data in db.Users.select():
                user = user_data.to_dict()
                user.pop('id')
                user_id = user.pop("tg_id")
                self._users[user_id] = user
    
                if user['times'] is not None:
                    self._add_times_to_queue(user_id, user['times'])
        botLogger.debug(f'User list is created - {self._users}')


    def _add_times_to_queue(self, user_id: int, times_in_minutes: list) -> None:
        times = []
        #minutes to datetime.time
        for time_in_min in times_in_minutes:
            hour = time_in_min//60
            minutes = time_in_min%60
            times.append(datetime.time(hour=hour, minute=minutes))

        for time in times:
            self._times_queue.run_daily(callback=self._callback, time=time,
                                        chat_id=user_id, name=str(user_id))


    def _delete_times_from_queue(self, user_id: int) -> bool:
        user_jobs = self._times_queue.get_jobs_by_name(str(user_id))

        if not user_jobs:
            return False

        for job in user_jobs:
            job.schedule_removal()
        return True

    def add_user_if_not_exists(self, user_id: int) -> bool:
        if self._users.get(user_id) is not None:
            return False

        self._users[user_id] = {"waiting":False, "times": None, "timezone": None, 
                        "sets_per_day": config.standart_quant, 'interval':config.std_time_interval}
        user = self._users[user_id]
        with orm.db_session:
            db.Users(tg_id=user_id, waiting=user["waiting"], sets_per_day=user['sets_per_day'],
                           interval=user['interval'])
            return True

    def delete_user(self, user_id: int) -> None:
        self._delete_times_from_queue(user_id)
        self._users.pop(user_id)
        
        with orm.db_session:
            user = db.Users.select(lambda user: user.tg_id==user_id).first()
            user.learned.clear()
            user.delete()      

    def update_timezone(self, user_id: int, user_hour: int) -> None:
        timezone = abs(user_hour - datetime.datetime.utcnow().hour)
        if timezone > 12: timezone = 24 - timezone
        timezone*=60#convert to minutes
        self._users[user_id]['timezone'] = timezone
        self._update_user_data(user_id)

    def update_interval(self, user_id:int, interval: tuple) -> None:
        user = self._users[user_id]
        user['interval'] = tuple(time*60 for time in interval)#times in minutes
        self._update_user_data(user_id)


    def _update_user_data(self, user_id: int) -> None:
        '''Приводит в соответсвие всю информацию о пользователе, и обновляет бд'''
        #update times
        user = self._users[user_id]
        interval = user['interval']
        continuous = abs(interval[1]-interval[0])
        timezone = user['timezone']
        user_quant = user['sets_per_day']
        new_times = range(interval[0]-timezone, interval[1]-timezone, continuous//user_quant)
        new_times = [t for t in new_times]

        self._delete_times_from_queue(user_id)
        user["times"] = new_times
        self._add_times_to_queue(user_id, new_times)

        with orm.db_session:
            user_db = db.Users.select(lambda u: u.tg_id == user_id).first()
            user_db.set(**user)

    def is_waiting(self, user_id: int) -> bool:
        return self._users[user_id]['waiting']

    def update_quant(self, user_id: int, quant: int) -> None:
        user = self._users[user_id]
        user['sets_per_day'] = quant
        self._update_user_data(user_id)

    def wait_message(self, user_id: int) -> None:
        status = self._users[user_id]['waiting']
        if status is True:
            botLogger.warning(f'Error in wait_message func.{user_id} status allready is True')

        self._users[user_id]['waiting'] = True
        botLogger.debug(f"user status {user_id} is changed to {status}")

    def stop_waiting(self, user_id: int) -> None:
        status = self._users[user_id]['waiting']
        if status is False:
            botLogger.warning(f'Error in stop_waiting func.{user_id} status allready is False')

        self._users[user_id]['waiting'] = False
        botLogger.debug(f"user status {user_id} is changed to {status}")
                

class Bot:
    user_list = None
    application = None

    def __init__(self):
        self.application = ApplicationBuilder().token(config.token).build()

        start_handler = CommandHandler('start', self.start)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.message)
        times_handler = CommandHandler(config.set_time_interval, self.set_times)
        timezone_handler = CommandHandler(config.set_timezone, self.set_timezone)
        quant_handler = CommandHandler(config.set_quantity, self.quant_handler)
        callbak_handler = CallbackQueryHandler(self.keyboard_callback)
        status_handler = ChatMemberHandler(self.set_user_status)
        set_resp = CommandHandler(config.send_set, self.set_resp)

        self.application.add_handler(start_handler)
        self.application.add_handler(message_handler)
        self.application.add_handler(timezone_handler)
        self.application.add_handler(times_handler)
        self.application.add_handler(quant_handler)
        self.application.add_handler(callbak_handler)
        self.application.add_handler(set_resp)
        self.application.add_handler(status_handler)

        self.user_list = User_list(self.application.job_queue, self.callback_for_sending)

    def run_bot(self):
        if config.webhook:
            self.application.run_webhook(**config.webhook_params)
    
        else:
            self.application.run_polling()

    async def callback_for_sending(self, context: CallbackContext):
        await context.bot.send_message(chat_id=context.job.chat_id, text=messages.set_greetings)
        await self.send_set(context.job.chat_id, context.bot)

    async def set_resp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.send_set(update.effective_chat.id, context.bot)

    async def send_set(self, chat_id, bot):
        with orm.db_session:
            user = orm.select(u for u in db.Users if u.tg_id == chat_id).first()
            not_learned_sets = (s for s in db.Sets if not s.learned.select(lambda l: l.user_id == user))

            set_of_words = orm.select(not_learned_sets).random(1)
            set_of_words = next(iter(set_of_words))
            
            db.Learned_words(user_id=user, set_id=set_of_words)

            set_message = []
            for word in set_of_words.word.select():
                message = messages.set_word_part.format(
                    word=word.name,
                    translation=word.translation,
                    )

                if word.examples != '':
                    example_part = messages.set_example_part.format(
                        example=word.examples
                        )

                    message = '\n'.join([message, example_part])

                set_message.append(message)


        await bot.send_message(chat_id=chat_id, text='\n\n'.join(set_message))


    async def get_menu(self, query: str, update, context):
        menu = Menu(query)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=menu.text,
                                       reply_markup=menu.keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.start_message)
        #await self.get_menu("timezone;;;;;", update, context)
        await self.set_timezone(update, context, reg=True)

    async def set_times(self, update: Update, context: ContextTypes.DEFAULT_TYPE, reg=False):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.set_times)
        await self.get_menu(f'times;;;;;;{int(reg)}', update, context)

    async def set_user_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_status = update.my_chat_member.new_chat_member.status
        botLogger.debug(f'User {update.effective_chat.id} set status to {user_status}')
        
        if user_status == ChatMember.MEMBER:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.greeting)
            self.user_list.add_user_if_not_exists(update.effective_chat.id)
            botLogger.debug('Added new user to db.')

        elif user_status == ChatMember.BANNED:
            self.user_list.delete_user(update.effective_chat.id)
            botLogger.debug(f'user {update.effective_chat.id} was deleted')

    async def set_timezone(self, update: Update, context: ContextTypes.DEFAULT_TYPE, reg=False):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.set_timezone)
        await self.get_menu(f'timezone;;;;;;{int(reg)}', update, context)

    async def quant_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.set_quant)
        self.user_list.wait_message(update.effective_chat.id)
        
    async def set_quant(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_list.update_quant(update.effective_chat.id, int(update.message.text))
        self.user_list.stop_waiting(update.effective_chat.id)
        
        quant = int(update.message.text)
        text = update.message.text + ' раз'
        
        if quant%10 in (2,3,4) and quant//10 != 1:
            text = text + 'а'

        text = messages.set_quant_confirm.format(text)
        
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text=text
                                        )

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_chat.id

        botLogger.debug(f'message from {user_id} have handled')
        
        if self.user_list.is_waiting(user_id):
            botLogger.debug(f'message from {user_id} is expected.')
            if re.fullmatch(r'[1-9]', update.message.text):
                await self.set_quant(update, context)

            else:
                await context.bot.send_message(chat_id=user_id, text=messages.wrong_format)

            return

        await context.bot.send_message(chat_id=user_id, text=messages.unknown)

    async def keyboard_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        botLogger.debug(f'For user {update.effective_chat.id} menu is changed')
        menu = Menu(query.data)

        if menu.is_acepted:
            await context.bot.edit_message_text(text=menu.text, chat_id=query.message.chat_id,
                                            message_id=query.message.message_id)
            
            if menu.kb_type == 'times':
                self.user_list.update_interval(query.message.chat_id, menu.result)
                
                if menu.reg == '1':
                    await self.quant_handler(update, context)

            elif menu.kb_type == 'timezone':
                self.user_list.update_timezone(query.message.chat_id, menu.result)

                if menu.reg == '1':

                    await self.set_times(update, context, reg=True)

            
            return

        if menu.keyboard is None:
            await query.answer()
            return

        await context.bot.edit_message_text(text=menu.text, chat_id=query.message.chat_id,
                                            message_id=query.message.message_id,
                                            reply_markup=menu.keyboard)


class Menu:

    result = None
    text = None
    keyboard = None
    is_acepted = False
    reg = None

    def __init__(self, query):
        self.kb_type, action, cur_hour, cur_button, start_time, end_time, self.reg = query.split(";")
        botLogger.debug(f'Keyboard callback: {query}')
        time = datetime.datetime.utcnow()
        minutes = time.minute

        match self.kb_type:
            case "timezone":
                message = '{hour:0>2}:{minutes:0>2}'###
                #при генерации начального меню
                if cur_hour == '':
                    cur_hour = time.hour + 3 #MSK time
                    botLogger.debug(f'Curent hour in first timezone message: {cur_hour}')
                #В случае callback
                else:
                    cur_hour = int(cur_hour)

                switch = False

            case "times":
                #при генерации начального меню
                if cur_hour == '':
                    start_time = 11
                    end_time = 19
                    message = '{hour:0>2}:00-{end_time:0>2}:00' 
                    left_button = '^'
                    right_button = ' '
                    cur_hour = start_time
                    cur_button = 'left'
                #В случае callback
                else:
                    cur_hour = int(cur_hour)
                    start_time = int(start_time)
                    end_time = int(end_time)
        
                switch = True

        match action:
            case '+':
                cur_hour+=1

            case '-':
                cur_hour-=1

            case 'left':
                if cur_button != action:
                    end_time = cur_hour
                    cur_hour = start_time
                    cur_button = 'left'
                else: return

            case 'right':
                if cur_button != action:
                    start_time = cur_hour
                    cur_hour = end_time
                    cur_button = 'right'
                else: return
            
            case 'accept':
                self.is_acepted = True

                if self.kb_type == 'timezone':
                    self.result = cur_hour
                    self.text = messages.accepted_timezone.format(self.result)

                elif self.kb_type == 'times':
                    if cur_button == 'right':
                        end_time = cur_hour
                    elif cur_button == 'left':
                        start_time = cur_hour

                    self.result = (start_time, end_time)
                    self.text = messages.accepted_times.format(start_time, end_time)

                return

        if cur_hour>23:
            cur_hour -= 24
        elif cur_hour<0:
            cur_hour += 24

        #Проверка текущей кнопки в свитче
        if cur_button == 'left':
            left_button = '^'
            right_button = ' '
            message = '{hour:0>2}:00-{end_time:0>2}:00'

        elif cur_button == 'right':
            left_button = ' '
            right_button = '^'
            message = '{start_time:0>2}:00-{hour:0>2}:00'

        message = message.format(start_time=start_time, end_time=end_time, hour=cur_hour, minutes=minutes)

        self.text = message

        callback = f'{self.kb_type};~;{cur_hour};{cur_button};{start_time};{end_time};{self.reg}'

        if switch:
            kb = [
            [InlineKeyboardButton(text=left_button, callback_data=callback.replace('~', 'left')),
            InlineKeyboardButton(text=right_button, callback_data=callback.replace('~', 'right'))]
            ]
        else:
            kb = []

        kb.append(
            [InlineKeyboardButton(text='<', callback_data=callback.replace('~', '-')),
            InlineKeyboardButton(text=u'\U00002705', callback_data = callback.replace('~', 'accept')),
            InlineKeyboardButton(text='>', callback_data=callback.replace('~', '+'))]
            )


        self.keyboard = InlineKeyboardMarkup(kb)


if __name__ == '__main__':
    bot = Bot()
    bot.run_bot()
