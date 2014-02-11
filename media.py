'''
Mesix tornado server

Written by github.com/aikbix


'''

from functools import partial
from hsaudiotag import auto
from os import walk, urandom
from os.path import join, dirname
from pymongo import MongoClient
from subprocess import Popen, PIPE
from threading import Thread
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.web import Application
from tornado.websocket import WebSocketHandler

try:
    import ujson as json
except ImportError:
    import json


# List of clients
LISTENERS = []
# Enable all threads as daemons
# Thread = partial(Thread, daemon=1)

# Enabling daemons doesn't work in my environment (-Mustafa)
Thread = partial(Thread)



class PropagationService(object):
    '''
    Handles multi-client communication.
    '''

    def _propagate(self, mapper):
        '''
        Propagates data to all clients.
        TODO make asynchronous.
        '''

        for listener in LISTENERS:
            listener.send(mapper)

    def propagate(self, mapper):
        '''
        Instantiates a thread to handle message propagation.
        '''

        Thread(target=self._propagate, args=(mapper,)).start()


def global_config():
    '''
    Configuration read from the config.json. This feels a little messy.
    '''

    config_path = join(dirname(__file__), 'config.json')
    config = json.loads(open(config_path).read())

    config['music_path'] = config.get('music_path') or '~/Music'

    return config


class MusicDatabase(PropagationService):
    '''
    Interface for the music database. Handles both queries and writes.
    '''

    def __init__(self, config=global_config()):
        self._mongo_client = MongoClient()
        self.db = self._mongo_client.Music
        self.collection = self.db.music

        self._config = config
        # Partial regex pattern for supported file extensions.
        self._extensions = '|'.join([
            i.lower() for i in self._config['extensions']
        ])

        # Update the library
        Thread(target=self.add_folder, args=(config['music_path'],)).start()

    def get_media(self, path):
        '''
        Retrieves a song based off of its path.
        '''

        return dict(self.collection.find_one({'path': path},
                                             fields={'_id': 0}))

    @property
    def media_tree(self):
        '''
        List of playable songs.
        '''

        return self._media_list

    def cache_folder(self, walk_tuple):
        '''
        Cache folder contents in a database.
        '''
        folder = walk_tuple[0]
        files = walk_tuple[2]

        media_files = (join(folder, file)
                       for file in files
                       if file.split('.')[-1] in self._extensions)

        for file in media_files:
            self.add_file(file)

    def add_file(self, file_path):
        '''
        Takes the path of a song and writes its information to the database.
        '''

        meta = auto.File(file_path)
        metadata = {
            'artist': meta.artist,
            'album': meta.album,
            'title': meta.title,
            'path': file_path,
            'genre': meta.genre,
            'duration': meta.duration,
        }

        self.collection.update(metadata, metadata, upsert=True)
        self.propagate({'metadata': metadata})

    def add_folder(self, path=None):
        '''
        Adds an entire folder of songs to the database.
        '''

        if not path:
            path = self._config['music_path']

        # Walk through entire music directory (could take awhile)
        walk_list = list(walk(path))
        # Pool of workers to read the walk_list
        for walk_tuple in walk_list:
            self.cache_folder(walk_tuple)

    def library(self):
        '''
        The entire song library.
        '''

        result = list(self.collection.find(fields={'_id': 0}))

        return {'library': result}

    def filter(self, key, query, all=False):
        '''
        Get a unique list of values for a key from a query. This could be
        extended to except multiple keys. Set "all" to true to return all keys.
        '''

        fields = {'_id': 0}

        if not all:
            fields[key] = 1

        print(fields)

        result = self.collection.find(query, fields=fields)

        if all:
            value = list(result)
        else:
            value = set(d[key] for d in result)

        return {'filter': {key: value}}


class Player(PropagationService):
    '''
    A wrapper over mplayer. Handles media playing.
    TODO Playlists and queues.
    '''

    def __init__(self, config=global_config()):
        self._config = global_config()
        self.db = MusicDatabase()

        self._status_dict = {
            'playing': False,
            'queue': [],
            'current': {},
        }

    @property
    def running(self):
        '''
        Is music playing?
        '''

        if hasattr(self, '_media'):
            return True
        else:
            return False

    def stop(self):
        '''
        Stops music from playing.
        '''

        self.issue_command('stop')
        self._media.kill()
        del self._media

    def play(self, file):
        '''
        Plays music from a specified file path.
        '''

        result = self.db.get_media(file['path'])

        if result:
            if self.running:
                self.stop()

            self._media_thread = Thread(target=self._play_media,
                                        args=(result['path'],))
            self._media_thread.start()

            self.propagate({
                'playing': True,
                'current': result,
            })
        else:
            return {'error': 'Song does not exist in database'}

    def pause(self):
        '''
        Pauses music.
        '''

        if hasattr(self, '_media'):
            self.issue_command('pause')
            self.propagate({'playing': not self.status['playing']})

    @property
    def status(self):
        '''
        Current state of the media player.
        '''

        return self._status_dict

    def _play_media(self, media):
        '''
        Creates a new pipe to mplayer and plays a specified song.
        '''

        self._media = Popen(['mplayer', '-slave', '-quiet', media],
                            stdout=PIPE, stderr=PIPE, stdin=PIPE)

    def issue_command(self, command):
        '''
        Issues a specified command to mplayer via STDIN.
        See: http://www.mplayerhq.hu/DOCS/tech/slave.txt
        '''

        stdout_commnand = bytes(command + '\n', encoding="UTF-8")
        self._media.stdin.write(stdout_commnand)

    def propagate(self, mapper):
        '''
        Overrides the original propagation method in order to update the player
        status before broadcasting its state.
        '''

        self._status_dict.update(mapper)

        super().propagate(mapper)


class WebPlayer(WebSocketHandler):
    '''
    Handles communication with WebSocket clients.
    '''

    # Media player
    player = Player()

    @property
    def gatekeeper(self):
        '''
        Keys mapped to functions that are allowed to be called.
        '''

        return {
            'play': self.player.play,
            'pause': self.player.pause,
            'add_folder': self.player.db.add_folder,
            'library': self.player.db.library,
            'filter': self.player.db.filter,
        }

    def on_message(self, message):
        '''
        Handles an incoming message.
        '''

        try:
            message = json.loads(message)
            function = message.get('function')
            arguments = message.get('args') or {}
            func = self.gatekeeper.get(function) or self._nothing
            result = func(**arguments) if arguments else func()
            print('--------------------------- In ---------------------------')
            print(message)
            if result:
                self.send(result)
        except Exception as e:
            print('--------------------- Error occurred ---------------------')
            print("Message recieved:")
            print(message)
            print('----------------------------------------------------------')
            print("Exception raised:")
            print(e)
            self.send({'message': e})

    def _nothing(self):
        '''
        Empty function call for fringe cases.
        '''

        return False

    def on_close(self):
        '''
        Removes client from listeners upon socket close.
        '''

        LISTENERS.remove(self)

    def open(self):
        '''
        Adds client to listeners and sends it the player state upon socket
        open.
        '''

        LISTENERS.append(self)
        self.send(self.player.status)

    def send(self, message):
        '''
        Serializes data into a JSON format and sends it to the client.
        '''

        print('--------------------------- Out ---------------------------')
        print(message)
        if message:
            self.write_message(json.dumps(message))


def run(port=8080):
    '''
    Run an instance of the web player.
    '''
    settings = {
        'auto_reload': True,
        'xsrf_cookies': True,
        'cookie_secret': urandom(64),
        'login_url': r'/login',
    }

    application = Application([
        (r'/player', WebPlayer),
    ], **settings)

    print("Server listening on {0}".format(port))

    HTTPServer(application).listen(port)
    IOLoop.instance().start()


if __name__ == '__main__':
    run()
