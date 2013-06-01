/*global document, WebSocket, console, angular*/
'use strict';

var app = angular.module('mesix', []);

app.service('socket', function ($rootScope) {
    var ws = new WebSocket("ws://localhost:8080/player"),
        queue = [];

    ws.onmessage = function (payload) {
        var message = JSON.parse(payload.data),
            key;

        for (key in message) {
            if (message.hasOwnProperty(key)) {
                $rootScope.$emit(key, message[key]);
            }
        }
    };
    
    ws.handle_queue = function () {
        var index;
        
        for (index = 0; index < queue.length; index += 1) {
            ws.send(queue[index]);
        }

        queue = [];
    };

    ws.onopen = function () {
        ws.handle_queue();
    };

    return {
        emit: function (fn, args) {
            var payload = JSON.stringify({
                'function': fn,
                'args': args || {}
            });
            if (ws.readyState) {
                ws.send(payload);
            // Queue the item if the websocket has not been initialized.
            } else {
                queue.push(payload);
            }
        },
        
        on: function event(name, fn) {
            $rootScope.$on(name, function (event, args) {
                $rootScope.$apply(function () {
                    fn(args);
                });
            });
        }
    };
});


function AudioCtrl($scope, socket) {
    $scope.filters = {
        album: null,
        artist: null,
        song: null
    };
    

    //-------------------------------------------------------------------------
    // UI functions
    //-------------------------------------------------------------------------
    

    function updatePauseButton(status) {
        if (status) {
            $scope.control_state = 'II';
        } else {
            $scope.control_state = ">";
        }
    }

    //-------------------------------------------------------------------------
    // Events
    //-------------------------------------------------------------------------
    

    socket.on('library', function (list) {
        $scope.library = list;
    });

    socket.on('playing', function (status) {
        updatePauseButton(status);
    });

    socket.on('queue', function (queue) {
        $scope.queue = queue;
    });
    
    socket.on('current', function (song) {
        $scope.current = song;
    });
    
    socket.on('metadata', function (metadata) {
        //$scope.library.update(metadata);
    });
    
    socket.on('message', function (message) {
        $scope.message = message;
    });

    socket.on('filter', function (message) {
        var filter;

        for (filter in message) {
            if (message.hasOwnProperty(filter)) {
                $scope[filter] = message[filter];
            }
        }
    });


    //-------------------------------------------------------------------------
    // Watchers
    //-------------------------------------------------------------------------
    
    $scope.$watch('filters.artist', function (oldFilter, newFilter) {
        if (newFilter) { //!== oldFilter && newFilter) {
            $scope.emitFilter('album', newFilter[0]);
        }
    });

    //-------------------------------------------------------------------------
    // Emitters
    //-------------------------------------------------------------------------
    

    $scope.emitPlay = function (song) {
        // Send explicit query, we dont want to modify any state.
        socket.emit('play', {
            file: {
                album: song.album,
                artist: song.artist,
                duration: song.duration,
                genre: song.genre,
                path: song.path,
                title: song.title
            }
        });
    };
    
    $scope.emitPause = function () {
        socket.emit('pause');
    };
    
    $scope.emitAddFolder = function () {};
    
    $scope.emitLibrary = function () {};

    $scope.emitFilter = function (key, query, all) {
        var args = {key: key};
        
        if (all) {
            args.all = true;
        }

        if (typeof (query) === String) {
            args.query[key] = query;
        } else {
            args.query = query;
        }

        socket.emit('filter', args);
    };

    $scope.filterAlbumsByArtist = function (artistName) {
        $scope.emitFilter('album', {artist: artistName});
    };
    
    $scope.filterSongsByAlbum = function (albumName) {
        $scope.emitFilter('title', {album: albumName}, true);
    };

    // Initial payload
    socket.emit('filter', {key: 'artist', query: {}});
}
