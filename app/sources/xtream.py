#!/usr/bin/env python3
"""
Xtream Codes API Source Module

This module implements Xtream Codes API integration for fetching live streams,
VOD content, and series information from Xtream-compatible providers.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import logging
from typing import List, Dict, Any
from app.models import StreamInfo
from app.sources.base import StreamSource

# setup the logger
logger = logging.getLogger(__name__)

"""
XStream Codes API source

Fetches streams from Xtream Codes API providers including live, VOD, and series.
"""
class XtreamSource(StreamSource):
    
    """
    Initialize the XtreamSource
    
    Sets up API endpoint and authentication parameters.
    
    @param args: Positional arguments passed to parent class
    @param kwargs: Keyword arguments passed to parent class
    """
    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_url = f"{self.config.url}/player_api.php"
        self.base_params = {
            'username': self.config.username,
            'password': self.config.password
        }
    
    """
    Fetch streams from Xtream API
    Retrieves user info, live streams, VOD streams, and series from the provider.
    
    @return list: List of StreamInfo objects from all Xtream API endpoints
    """
    async def _fetch_streams(self) -> List[StreamInfo]:

        # hold the streams
        streams = []
        
        # Fetch user info first
        await self._fetch_user_info()
        
        # Fetch all stream types
        streams.extend(await self._fetch_live_streams())
        streams.extend(await self._fetch_vod_streams())
        streams.extend(await self._fetch_series())
        
        # return them
        return streams
    
    """
    Fetch user information from Xtream API
    
    Retrieves user account details including expiration date.
    
    @return None
    """
    async def _fetch_user_info(self):

        # let's try to fetch
        try:

            # use our session to get the user data
            async with self.session.get(self.api_url, params=self.base_params) as resp:

                # if we have a valid response code
                if resp.status in (200, 206, 304):

                    # hold the data
                    user_data = await resp.json()

                    # make sure what we need is in the response, and then set it up
                    if 'user_info' in user_data:
                        self.config.exp_date = user_data['user_info'].get('exp_date', '9999999999')

        # whoopsie... log the exception and set a default expiry
        except Exception as e:
            logger.error(f"Failed to fetch user info: {e}")
            self.config.exp_date = '9999999999'

        # Build EPG URL
        self.config.epg_url = f"{self.config.url}/xmltv.php?username={self.config.username}&password={self.config.password}"
    
    """
    Fetch live streams from Xtream API
    
    Retrieves all available live TV channels from the provider.
    
    @return list: List of StreamInfo objects for live streams
    """
    async def _fetch_live_streams(self) -> List[StreamInfo]:

        # hold the streams
        streams = []
        
        # setup the parameters
        params = self.base_params.copy()
        params['action'] = 'get_live_streams'
        
        # try to get all live streams
        try:
        
            # utilize our session and get all live streams
            async with self.session.get(self.api_url, params=params) as resp:
        
                # make sure we have a valid response
                if resp.status in (200, 206, 304):

                    # we do, so hold the data
                    data = await resp.json()

                    # for each stream item in the response
                    for stream in data:

                        # format the stream url
                        stream_url = f"{self.config.url}/live/{self.config.username}/{self.config.password}/{stream.get('stream_id', '')}.ts"
                        
                        # Get the base name and apply prefix/suffix
                        base_name = stream.get('name', '')
                        display_name = f"{self.config.stream_name_prefix}{base_name}{self.config.stream_name_suffix}"

                        # append it all to the stream info
                        streams.append(StreamInfo(
                            name=base_name,
                            url=stream_url,
                            source_id=self.config.name,
                            category=stream.get('category_name', ''),
                            group=stream.get('category_name', ''),
                            logo=stream.get('stream_icon', ''),
                            stream_id=str(stream.get('stream_id', '')),
                            tvg_id=stream.get('epg_channel_id', ''),
                            tvg_name=base_name,
                            epg_channel_id=stream.get('epg_channel_id', ''),
                            parent_code=str(stream.get('parent_code', '')),
                            display_name=display_name
                        ))

        # whoopsie.. log the error
        except Exception as e:
            logger.error(f"Failed to fetch live streams: {e}")
        
        # return the streams
        return streams

    """
    Fetch VOD (Video on Demand) streams from Xtream API
    Retrieves all available movies and video content from the provider.
    
    @return list: List of StreamInfo objects for VOD content
    """
    async def _fetch_vod_streams(self) -> List[StreamInfo]:

        # hold the streams
        streams = []
        
        # hold the parameters
        params = self.base_params.copy()
        params['action'] = 'get_vod_streams'
        
        # try to get all vod streams
        try:

            # utilize our session and get all live streams
            async with self.session.get(self.api_url, params=params) as resp:
            
                # make sure we have a valid response
                if resp.status in (200, 206, 304):
            
                    # we do, so hold the data
                    data = await resp.json()

                    # loop the streams in the response
                    for stream in data:

                        # setup the stream URL
                        stream_url = f"{self.config.url}/movie/{self.config.username}/{self.config.password}/{stream.get('stream_id', '')}.mp4"
                        
                        # Get the base name and apply prefix/suffix
                        base_name = stream.get('name', '')
                        display_name = f"{self.config.stream_name_prefix}{base_name}{self.config.stream_name_suffix}"

                        # append the stream data
                        streams.append(StreamInfo(
                            name=base_name,
                            url=stream_url,
                            source_id=self.config.name,
                            category=stream.get('category_name', ''),
                            group=stream.get('category_name', ''),
                            logo=stream.get('stream_icon', ''),
                            stream_id=str(stream.get('stream_id', '')),
                            tvg_name=base_name,
                            display_name=display_name
                        ))

        # whoopsie.. log the error
        except Exception as e:
            logger.error(f"Failed to fetch VOD streams: {e}")
        
        # return the streams
        return streams

    
    """
    Fetch series from Xtream API
    
    Retrieves all available TV series from the provider.
    
    @return list: List of StreamInfo objects for series content
    """
    async def _fetch_series(self) -> List[StreamInfo]:
    
        # hold the streams
        streams = []
        
        # setup the parameters
        params = self.base_params.copy()
        params['action'] = 'get_series'
        
        # try to get all series streams
        try:

            # utilize our session and get all live streams
            async with self.session.get(self.api_url, params=params) as resp:

                # make sure we have a valid response
                if resp.status in (200, 206, 304):

                    # we do, so hold the data
                    data = await resp.json()

                    # loop the streams in the response
                    for series in data:

                        # setup the necessary data
                        series_id = series.get('series_id', '')
                        series_name = series.get('name', '')
                        
                        # Get the base name and apply prefix/suffix
                        base_name = f"{series_name} (Series)"
                        display_name = f"{self.config.stream_name_prefix}{series_name}{self.config.stream_name_suffix} (Series)"

                        # append to our stream info
                        streams.append(StreamInfo(
                            name=base_name,
                            url=f"{self.config.url}/series/{self.config.username}/{self.config.password}/{series_id}.ts",
                            source_id=self.config.name,
                            category=series.get('category_name', ''),
                            group=series.get('category_name', ''),
                            logo=series.get('cover', ''),
                            stream_id=str(series_id),
                            tvg_name=series_name,
                            display_name=display_name
                        ))

        # whoopsie.. log the error
        except Exception as e:
            logger.error(f"Failed to fetch series: {e}")
        
        # return the streams
        return streams
    