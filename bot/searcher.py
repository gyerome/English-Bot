from bs4 import BeautifulSoup as bs
import database as db
from pony import orm
import requests
import logging
import signal
import random
import config
import time
import re

logging.basicConfig(level=logging.INFO, filename=config.log_path+'searcher.log', filemode='w',
                    format=config.logging_format
)
searcherLogger = logging.getLogger(__name__)

def getSoup(url:str) -> bs:
    page=requests.get(url, headers=config.headers)
    return bs(page.text, "lxml")


def getSet(word_name: str) -> list:
    dict_url = "https://wooordhunt.ru/word/"
    url = dict_url + word_name
    soup = getSoup(url)
    translation = None
    part_of_speach = None
    examples = None

    try:
        related = soup.find("h3", string="Возможные однокоренные слова")
        related = related.next_sibling.next_sibling.find_all("a")
        related = [i.string for i in related]#Получение содержимого тегов

    except(AttributeError) as e:
        return None

    related.append(word_name)
    res = []

    searcherLogger.debug(f'find related words: {related}')
    if len(related) > 6:
        related = related[0:6]

    for name in related:
        with orm.db_session:
            isWordInDB = orm.exists(w.name for w in db.Dictionary if w.name == name)
            
            if isWordInDB:
                continue

        url = dict_url + name
        soup = getSoup(url)
        try:
            translation = soup.find('div', class_="t_inline_en").string.split(',')[0]
            part_of_speach = soup.find('h4', class_=re.compile(r"pos_item*")).stripped_strings
            #генератор со всеми строками тега
            part_of_speach = next(part_of_speach)#первая строка тега
            part_of_speach = re.sub(',', '', part_of_speach)
            examples = soup.find_all("p", class_=lambda c: c == "ex_o" and bool(random.getrandbits(1)), 
                style=False)# находит несколько случайных примеров на английском
            examples = [next(example.stripped_strings) for example in examples[:1]]
            isComplete = True

        except (AttributeError, ValueError) as e:
            isComplete = False
            searcherLogger.info(f"Can't get all information about the {name}. {e}."
                                f'translation: {translation}.'
                                f'part of speach: {part_of_speach}.'
                                f'examples: {examples}'
            )

        if isComplete:
            res.append({'name':name, "translation":translation,
                        'part_of_speach':part_of_speach, "examples":examples})
        time.sleep(config.srch_delay)
    return res


def search():
    queue = [f"https://en.wikipedia.org"]
    visited_urls = set()

    with orm.db_session:
        for url in db.Urls.select():
            visited_urls.add(url.url)
            url.delete()
        orm.commit()

    @orm.db_session
    def terminate(sig, frame):
        for url in visited_urls:
            db.Urls(url=url)
        orm.commit()
        exit()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    while len(queue) != 0:
        url = queue.pop(0)
        visited_urls.add(url)
        soup = getSoup(url)

        for p_tag in soup.find_all('p'):
            text = p_tag.get_text()
            words = re.split(r"[ ,\.!?:;\'\"()-]", text)
            

            for word in words:
                if re.fullmatch(r'[A-z]{5,}', word) is None:
                    continue
                
                set_related = getSet(word.lower())

                if set_related is None or set_related == []:
                    continue
                
                if len(set_related) < 3:
                    continue

                quantity = len(set_related)

                with orm.db_session:
                    related = db.Sets(quantity=quantity)
                    for w in set_related:
                        if w["examples"] is not None:
                            w['examples'] = "/".join(w["examples"])

                        db.Dictionary(name=w["name"], translation=w["translation"], 
                                      part_of_speach=w["part_of_speach"], set_id=related,
                                      examples=w['examples'])

        #находим все относительные(значит указывающие на статьи вики) ссылки
        links = soup.find_all('a', href=lambda url: not "https://" in url and not url in visited_urls)
        queue.extend(links)

    searcherLogger.warning('Urls is over')

if __name__ == '__main__':
    search()