from pony import orm


path='../bot.db'
db = orm.Database()
orm.set_sql_debug(False)


class Users(db.Entity):
    tg_id = orm.Required(int, unique=True)
    sets_per_day = orm.Optional(int)
    learned = orm.Set("Learned_words")
    times = orm.Optional(orm.IntArray)
    timezone = orm.Optional(int)
    interval = orm.Optional(orm.IntArray)
    waiting = orm.Required(bool)
        
class Sets(db.Entity):
    word = orm.Set('Dictionary')
    quantity = orm.Required(int)
    learned = orm.Set("Learned_words")


class Dictionary(db.Entity):
    part_of_speach = orm.Required(str)
    name = orm.Required(str)
    translation = orm.Required(str)
    examples = orm.Optional(str)#Some examples is in one string
    set_id = orm.Required('Sets')

class Learned_words(db.Entity):
    user_id = orm.Required("Users")
    set_id = orm.Required("Sets")
    #complete = orm.Required(int)

class Urls(db.Entity):
    url = orm.Required(str)


if __name__ == '__main__':
    db.bind(provider="sqlite", filename=path, create_db=True)
    db.generate_mapping(create_tables=True)

else:
    db.bind(provider="sqlite", filename=path)
    db.generate_mapping()