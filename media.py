'''
TODO:
    Volume control
    Music stream
    Youtube/Soundcloud/Grooveshark integration
    User authentication
    Encryption
    Current song time
'''

from pymongo import MongoClient
from threading import Thread
from subprocess import Popen, PIPE
from tornado.websocket import WebSocketHandler
from tornado.ioloop import IOLoop
from tornado.httpserver import HTTPServer
from tornado.web import Application
from os.path import join, dirname
from os import walk, urandom
from hsaudiotag import auto
from functools import partial

try:
    import ujson as json
except ImportError:
    import json


# List of clients
LISTENERS = []
# Enable all threads as daemons
Thread = partial(Thread, daemon=1)


class PropagationService(object):
    '''
    Handles multi-client communication.
    '''

    def _propagate(self, mapper):
        for listener in LISTENERS:
            listener.send(mapper)

    def propagate(self, mapper):
        Thread(target=self._propagate, args=(mapper,)).start()


def global_config():
    config_path = join(dirname(__file__), 'config.json')
    config = json.loads(open(config_path).read())

    config['music_path'] = config.get('music_path') or '~/Music'

    return config


class MusicDatabase(PropagationService):
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
        Thread(target=self.add_folder).start()

    def get_media(self, path):
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
        if not path:
            path = self._config['music']

        # Walk through entire music directory (could take awhile)
        walk_list = list(walk(path))
        # Pool of workers to read the walk_list
        for walk_tuple in walk_list:
            self.cache_folder(walk_tuple)

    def library(self):
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
    Handles media playing.
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
        if hasattr(self, '_media'):
            return True
        else:
            return False

    def stop(self):
        self.issue_command('stop')
        self._media.kill()
        del self._media

    def play(self, file):
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
        if hasattr(self, '_media'):
            self.issue_command('pause')
            self.propagate({'playing': not self.status['playing']})

    @property
    def initial_payload(self):
        return self.status

        return payload

    @property
    def status(self):
        return self._status_dict

    def _play_media(self, media):
        self._media = Popen(['mplayer', '-slave', '-quiet', media],
                            stdout=PIPE, stderr=PIPE, stdin=PIPE)

    def issue_command(self, command):
        stdout_commnand = bytes(command + '\n', encoding="UTF-8")
        self._media.stdin.write(stdout_commnand)

    def propagate(self, mapper):
        self._status_dict.update(mapper)

        super().propagate(mapper)


class WebPlayer(WebSocketHandler):
    player = Player()

    @property
    def gatekeeper(self):
        return {
            'play': self.player.play,
            'pause': self.player.pause,
            'add_folder': self.player.db.add_folder,
            'library': self.player.db.library,
            'filter': self.player.db.filter,
        }

    def on_message(self, message):
        try:
            message = json.loads(message)
            print(message)
            function = message.get('function')
            arguments = message.get('args') or {}
            func = self.gatekeeper.get(function) or self._nothing
            #result = self.player.db.filter('album', 'ISAM')
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
            self.send({
                'message': e,
            })
    def _nothing(self):
        return False

    def on_close(self):
        LISTENERS.remove(self)

    def open(self):
        LISTENERS.append(self)
        self.send(self.player.initial_payload)

    def send(self, message):
        print('--------------------------- Out ---------------------------')
        print(message)
        if message:
            self.write_message(json.dumps(message))


def run(port=8080):
    #static_root = join(dirname(__file__), 'web', 'web_client.html')

    settings = {
        'auto_reload': True,
        'xsrf_cookies': True,
        'cookie_secret': urandom(64),
        'login_url': r'/login',
    }

    application = Application([
        #(r'/^', StaticFileHandler, {'path': static_root}),
        (r'/player', WebPlayer),
    ], **settings)

    print("Server listening on {0}".format(port))

    HTTPServer(application).listen(port)
    IOLoop.instance().start()


if __name__ == '__main__':
    run()
