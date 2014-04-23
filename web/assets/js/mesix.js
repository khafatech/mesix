/*global document, WebSocket, console, angular*/
'use strict';

var app = angular.module('mesix', []);


app.service('socket', function ($rootScope) {
    var // Connection to the server. TODO change this
        ws = new WebSocket("ws://localhost:8080/player"),
        // Items waiting to be sent to the server.
        queue = [];

    /**
     * @private
     * Handles recieved payload from the server.
     * @param {String} payload : JSON data recieved from the server.
     */
    ws.onmessage = function (payload) {
        var message = JSON.parse(payload.data),
            key;

        for (key in message) {
            if (message.hasOwnProperty(key)) {
                $rootScope.$emit(key, message[key]);
            }
        }
    };

    /**
     * @private
     * Handles any items in the current queue.
     */
    ws.handle_queue = function () {
        var index;
        
        for (index = 0; index < queue.length; index += 1) {
            ws.send(queue[index]);
        }

        queue = [];
    };

    /**
     * @private
     * Handles the connection to the server once opened. If there are any
     * queued queries, then they will be immediately handled upon the opening
     * of the websocket.
     */
    ws.onopen = function () {
        ws.handle_queue();
    };

    return {
        /**
         * Sends data to the server.
         * @param {String} fn : Function to be called.
         * @param {Object} args : Arguments for said function.
         */
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
        
        /**
         * Allows the creation of events based on the keys in the JSON data
         * recieved from the server.
         * @param {String} fn : Event to listen to.
         * @param {Function} fn : Function to be executed when event is fired.
         */
        on: function event(name, fn) {
            $rootScope.$on(name, function (event, args) {
                $rootScope.$apply(function () {
                    fn(args);
                });
            });
        }
    };
});


/**
 *  Controller for the music player. Yes this is a god object, it will be
 *  refractored later on.
 */
function AudioCtrl($scope, socket) {
    //-------------------------------------------------------------------------
    // UI functions
    //-------------------------------------------------------------------------
    
    $scope.control_state = "II";
    
    /**
     * Change pause button based on boolean value.
     * @param {Boolean} status : Play state.
     */
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
    

    /**
     * Handles library event.
     * @param {Array} list : List of songs in the library.
     */
    socket.on('library', function (list) {
        $scope.library = list;
    });

    /**
     * Handles playing status event, updates play/pause button accordingly.
     * @param {Boolean} status : Play state.
     */
    socket.on('playing', function (status) {
        updatePauseButton(status);
    });

    /**
     * Handles playing status event, updates play/pause button accordingly.
     * @param {Boolean} status : Play state.
     */
    socket.on('queue', function (queue) {
        $scope.queue = queue;
    });

    /**
     * Handles playing current event.
     * @param {Object} song : Currently playing song.
     */
    socket.on('current', function (song) {
        $scope.current = song;
    });
    
    /**
     * Handles metadata event. This is supposed to update the current
     * album/artist/song list, but it might be deprecated since there is no
     * use for it at the present moment
     * @param {Object} metadata : List of songs.
     */
    socket.on('metadata', function (metadata) {
        //$scope.library.update(metadata);
    });
    
    /**
     * Handles error messages recieved from the server
     * @param {String} message : A message from the server.
     */
    socket.on('message', function (message) {
        $scope.message = message;
    });


    /**
     * Handles filter events. Sets a filter variable in $scope so it can be
     * seen on the page. Currently, this might be a little dangerous, as it
     * could potentially override other variables in $scope, but angular
     * doesn't seem to update automatically with namespaces. 
     * @param {Array} message : A list of objects that represent a filter.
     */
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
    

    /**
     * Updates the viewable album on the page whenever the artist variable
     * changes. Note: an update in album will also trigger an update in
     * songs.
     * @param {Object} oldFilter : The previous filter.
     * @param {Object} newFilter : The new filter.
     */
    $scope.$watch('artist', function (oldFilter, newFilter) {
        if (newFilter !== oldFilter && newFilter) {
            $scope.emitFilter('album', newFilter[0]);
        }
    });


    //-------------------------------------------------------------------------
    // Emitters
    //-------------------------------------------------------------------------
    
    /**
     * Tells the server to play a specific song based on the given criteria.
     * @param {Object} song : A song.
     */
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
    
    /**
     * Tells the server to pause the current song.
     */
    $scope.emitPause = function () {
        socket.emit('pause');
    };
    
    /**
     * TODO Tells the server to add a folder to the library.
     */
    $scope.emitAddFolder = function () {};
    
    /**
     * TODO Requests the library from the server.
     */
    $scope.emitLibrary = function () {};

    /**
     * Requests all unique values from the server given the requested key and
     * search criteria
     * @param {String} key : Requested key.
     * @param {String|Object} query : Search criteria.
     * @param {Boolean} all : Specifies whether all keys should return or just 
     *                        the requested key.
     */
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

    /**
     * Request a filter for albums that fall under the currently selected
     * artist.
     * @param {String} artistName : Name of artist.
     */
    $scope.filterAlbumsByArtist = function (artistName) {
        $scope.emitFilter('album', {artist: artistName});
    };
    
    /**
     * Request a filter for songs that fall under the currently selected album.
     * @param {String} artistName : Name of artist.
     */
    $scope.filterSongsByAlbum = function (albumName) {
        $scope.emitFilter('title', {album: albumName}, true);
    };

    // Initial payload
    socket.emit('filter', {key: 'artist', query: {}});
}
