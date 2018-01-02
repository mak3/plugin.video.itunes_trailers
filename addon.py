#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#     Copyright (C) 2013 Tristan Fischer
#     Copyright (C) 2016 tknorris
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import sys
import xbmcplugin
import xbmcgui
import os
from lib import kodi
from lib.kodi import i18n
from lib import trailer_scraper
from lib import log_utils
from lib import utils
from lib import cache
from lib.url_dispatcher import URL_Dispatcher
from lib.trailer_scraper import BROWSER_UA
from lib.trakt_api import Trakt_API, TransientTraktError, TraktError, TraktAuthError
from lib.trakt_api import SECTIONS
from lib.utils import WATCHLIST_SLUG

def __enum(**enums):
    return type('Enum', (), enums)

MODES = __enum(
    MAIN='main', TRAILERS='trailers', PLAY_TRAILER='play_trailer', DOWNLOAD_TRAILER='download_trailer', AUTH_TRAKT='auth_trakt', SET_LIST='set_list',
    ADD_TRAKT='add_trakt'
)

url_dispatcher = URL_Dispatcher()
scraper = trailer_scraper.Scraper()

TRAILER_SOURCES = [scraper.get_all_movies, scraper.get_exclusive_movies, scraper.get_most_popular_movies, scraper.get_most_recent_movies]
CP_ADD_URL = 'plugin://plugin.video.couchpotato_manager/movies/add?title=%s'

@url_dispatcher.register(MODES.MAIN)
def show_movies():
    try: limit = int(kodi.get_setting('limit'))
    except: limit = 0
    try: source = int(kodi.get_setting('source'))
    except: source = 0
    list_data = utils.make_list_dict()
    for movie in get_movies(source, limit):
        label = movie['title']
        key = movie['title'].upper()
        if key in list_data:
            if 'year' not in movie or not movie['year'] or not list_data[key] or int(movie['year']) in list_data[key]:
                label = '[COLOR green]%s[/COLOR]' % (label)
        
        liz = utils.make_list_item(label, movie)
        liz.setInfo('video', movie)
        
        menu_items = []
        runstring = 'RunPlugin(%s)' % (CP_ADD_URL % (movie['title']))
        menu_items.append((i18n('add_to_cp'), runstring),)
        queries = {'mode': MODES.ADD_TRAKT, 'title': movie['title'], 'year': movie.get('year', '')}
        runstring = 'RunPlugin(%s)' % (kodi.get_plugin_url(queries))
        menu_items.append((i18n('add_to_trakt'), runstring),)
        liz.addContextMenuItems(menu_items, replaceItems=False)
        
        queries = {'mode': MODES.TRAILERS, 'movie_id': movie['movie_id'], 'location': movie['location'], 'poster': movie.get('poster', ''), 'fanart': movie.get('fanart', '')}
        liz_url = kodi.get_plugin_url(queries)
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), liz_url, liz, isFolder=True)
    utils.set_view('movies', set_sort=True)
    kodi.end_of_directory(cache_to_disc=False)

@cache.cache_function(cache_limit=8)
def get_movies(source, limit):
    return [movie for movie in TRAILER_SOURCES[source](limit)]

@url_dispatcher.register(MODES.TRAILERS, ['location'], ['movie_id', 'poster', 'fanart'])
def show_trailers(location, movie_id='', poster='', fanart=''):
    path = kodi.get_setting('download_path')
    for trailer in scraper.get_trailers(location, movie_id):
        trailer['fanart'] = fanart
        trailer['poster'] = poster
        stream_url = utils.get_best_stream(trailer['streams'], 'stream')
        download_url = utils.get_best_stream(trailer['streams'], 'download')
        label = trailer['title']
        if path:
            file_name = utils.create_legal_filename(trailer['title'], trailer.get('year', ''))
            if utils.trailer_exists(path, file_name):
                label += ' [I](%s)[/I]' % (i18n('downloaded'))
        else:
            file_name = ''
            
        liz = utils.make_list_item(label, trailer)
        liz.setProperty('isPlayable', 'true')
        del trailer['streams']
        liz.setInfo('video', trailer)

        menu_items = []
        queries = {'mode': MODES.DOWNLOAD_TRAILER, 'trailer_url': download_url, 'title': trailer['title'], 'year': trailer.get('year', '')}
        runstring = 'RunPlugin(%s)' % (kodi.get_plugin_url(queries))
        menu_items.append(('Download Trailer', runstring),)
        liz.addContextMenuItems(menu_items, replaceItems=False)
        
        queries = {'mode': MODES.PLAY_TRAILER, 'trailer_url': stream_url, 'thumb': trailer.get('thumb', ''), 'trailer_file': file_name}
        liz_url = kodi.get_plugin_url(queries)
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), liz_url, liz, isFolder=False)
    utils.set_view('movies', set_view=True)
    kodi.end_of_directory()

@url_dispatcher.register(MODES.PLAY_TRAILER, ['trailer_url'], ['thumb', 'trailer_file'])
def play_trailer(trailer_url, thumb='', trailer_file=''):
    path = kodi.get_setting('download_path')
    if path and trailer_file:
        local_file = utils.trailer_exists(path, trailer_file)
        if local_file:
            trailer_url = os.path.join(path, local_file)
    else:
        trailer_url += '|User-Agent=%s' % (BROWSER_UA)
        
    listitem = xbmcgui.ListItem(path=trailer_url, iconImage=thumb, thumbnailImage=thumb)
    try: listitem.setArt({'thumb': thumb})
    except: pass
    listitem.setPath(trailer_url)
    xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, listitem)
    
@url_dispatcher.register(MODES.DOWNLOAD_TRAILER, ['trailer_url', 'title'], ['year'])
def download_trailer(trailer_url, title, year=''):
    path = kodi.get_setting('download_path')
    while not path:
        ret = xbmcgui.Dialog().yesno(kodi.get_name(), i18n('no_download_path'), nolabel=i18n('cancel'), yeslabel=i18n('set_it_now'))
        if not ret:
            return

        kodi.show_settings()
        path = kodi.get_setting('download_path')
        
    file_name = utils.create_legal_filename(title, year)
    utils.download_media(trailer_url, path, file_name)

@url_dispatcher.register(MODES.ADD_TRAKT, ['title'], ['year'])
def add_trakt(title, year=''):
    trakt_api = Trakt_API(kodi.get_setting('trakt_oauth_token'), kodi.get_setting('use_https') == 'true', timeout=int(kodi.get_setting('trakt_timeout')))
    results = trakt_api.search(SECTIONS.MOVIES, title)
    try: results = [result for result in results if result['year'] is not None and int(result['year']) - 1 <= int(year) <= int(result['year'] + 1)]
    except: pass
    if not results:
        kodi.notify(msg=i18n('no_movie_found'))
        return
    
    if len(results) == 1:
        index = 0
    else:
        pick_list = [movie['title'] if movie['year'] is None else '%s (%s)' % (movie['title'], movie['year']) for movie in results]
        index = xbmcgui.Dialog().select(i18n('pick_a_movie'), pick_list)
        
    if index > -1:
        slug = kodi.get_setting('default_slug')
        name = kodi.get_setting('default_list')
        if not slug:
            result = utils.choose_list()
            if result is None:
                return
            else:
                slug, name = result
        
        item = {'trakt': results[index]['ids']['trakt']}
        if slug == WATCHLIST_SLUG:
            trakt_api.add_to_watchlist(SECTIONS.MOVIES, item)
        elif slug:
            trakt_api.add_to_list(SECTIONS.MOVIES, slug, item)
            
        movie = results[index]
        label = movie['title'] if movie['year'] is None else '%s (%s)' % (movie['title'], movie['year'])
        kodi.notify(msg=i18n('added_to_list') % (label, name))
        kodi.refresh_container()

@url_dispatcher.register(MODES.AUTH_TRAKT)
def auth_trakt():
    utils.auth_trakt()
 
@url_dispatcher.register(MODES.SET_LIST)
def set_list():
    result = utils.choose_list()
    if result is not None:
        slug, name = result
        kodi.set_setting('default_list', name)
        kodi.set_setting('default_slug', slug)

def main(argv=None):
    if sys.argv: argv = sys.argv
    queries = kodi.parse_query(sys.argv[2])
    log_utils.log('Version: |%s| Queries: |%s|' % (kodi.get_version(), queries), log_utils.LOGNOTICE)
    log_utils.log('Args: |%s|' % (argv), log_utils.LOGNOTICE)

    # don't process params that don't match our url exactly. (e.g. plugin://plugin.video.1channel/extrafanart)
    plugin_url = 'plugin://%s/' % (kodi.get_id())
    if argv[0] != plugin_url:
        return

    try:
        mode = queries.get('mode', None)
        url_dispatcher.dispatch(mode, queries)
    except (TransientTraktError, TraktError, TraktAuthError) as e:
        log_utils.log(str(e), log_utils.LOGERROR)
        kodi.notify(msg=str(e), duration=5000)

if __name__ == '__main__':
    sys.exit(main())
