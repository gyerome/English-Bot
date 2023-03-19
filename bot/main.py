from subprocess import Popen
import signal
import time

def stop(sig=None, frame=None):
    bot.terminate()
    if searcher.poll() is None:
        searcher.terminate()
    exit()

def main():
    global bot, searcher
    bot = Popen(['python', 'bot/bot.py'])
    
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    searcher = Popen(['python', 'bot/searcher.py'])
    while True:
        searcher.send_signal(signal.SIGSTOP)
        time.sleep(4*60*60)
        searcher.send_signal(signal.SIGCONT)
        time.sleep(600)

if __name__ == '__main__':
        main()