import os

headers = {'User-agent':'Mozilla/5.0'}

standart_quant = 2 #Количество слов в день
std_time_interval = (11*60, 19*60) #Время в которое можно отправлять

token = os.environ.get('TOKEN')
ip = os.environ.get('IP')

webhook = False
webhook_params = dict(cert='path to cert',
                      key='path to key',
                      listen = ip,
                      port = 80,
                      url_path = token,
                      webhook_url = f'https://{ip}/{token}'
                    )

#commands
set_timezone = 'timezone'
set_time_interval = 'times'
set_quantity = 'quant'
send_set = 'set'

logging_format = '%(asctime)s %(levelname)s:%(name)s:%(message)s'
log_path = 'logs/'

srch_delay = 2
