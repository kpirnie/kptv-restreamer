#!/usr/bin/env python3
"""
M3U Playlist Source Module

This module implements M3U/M3U8 playlist parsing and stream extraction.
It fetches playlists from HTTP URLs and parses EXTINF metadata.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import re, logging
from typing import List
from app.models import StreamInfo
from app.sources.base import StreamSource

# setup the logger
logger = logging.getLogger(__name__)

"""
M3U playlist source

Fetches and parses M3U/M3U8 playlists from HTTP URLs.
"""
class M3USource(StreamSource):
    
    """
    Fetch streams from M3U playlist
    Downloads the M3U playlist and parses it into StreamInfo objects.

    @return list: List of StreamInfo objects parsed from playlist
    """
    async def _fetch_streams(self) -> List[StreamInfo]:

        # setup the streams
        streams = []
        
        # try the requests
        try:

            # fire up the session to request the endpoint
            async with self.session.get(self.config.url) as resp:

                # if we have a valid response
                if resp.status in (200, 206, 304):

                    # get the response and parse it.
                    content = await resp.text()
                    streams = self._parse_m3u(content)
        
        # whoops... log the exception
        except Exception as e:
            logger.error(f"Failed to fetch M3U playlist: {e}")
        
        # return the streams
        return streams
    
    """
    Parse M3U playlist content
    Extracts stream information and EXTINF metadata from M3U playlist text.

    @param content: str Raw M3U playlist content
    @return list: List of StreamInfo objects with parsed metadata
    """
    def _parse_m3u(self, content: str) -> List[StreamInfo]:
        
        # hold the streams and the lines
        streams = []
        lines = content.strip().split('\n')
        
        # setup and hold the current info
        current_info = {}

        # loop over each line
        for line in lines:

            # strip start and end spaces
            line = line.strip()
            
            # if the line starts with the extinf
            if line.startswith('#EXTINF:'):

                # split it up on the ending comma
                parts = line.split(',', 1)

                # if there's a second part after the line, set the name
                if len(parts) == 2:
                    current_info['name'] = parts[1].strip()
                
                # setup the rest of the meta data
                if 'group-title=' in line:
                    match = re.search(r'group-title="([^"]*)"', line)
                    if match:
                        current_info['group'] = match.group(1)
                if 'tvg-logo=' in line:
                    match = re.search(r'tvg-logo="([^"]*)"', line)
                    if match:
                        current_info['logo'] = match.group(1)
                if 'tvg-id=' in line:
                    match = re.search(r'tvg-id="([^"]*)"', line)
                    if match:
                        current_info['tvg_id'] = match.group(1)
                if 'tvg-language=' in line:
                    match = re.search(r'tvg-language="([^"]*)"', line)
                    if match:
                        current_info['tvg_language'] = match.group(1)
                if 'tvg-country=' in line:
                    match = re.search(r'tvg-country="([^"]*)"', line)
                    if match:
                        current_info['tvg_country'] = match.group(1)
                if 'tvg-url=' in line:
                    match = re.search(r'tvg-url="([^"]*)"', line)
                    if match:
                        current_info['tvg_url'] = match.group(1)
                if 'radio=' in line:
                    match = re.search(r'radio="([^"]*)"', line)
                    if match:
                        current_info['radio'] = match.group(1)
                if 'aspect-ratio=' in line:
                    match = re.search(r'aspect-ratio="([^"]*)"', line)
                    if match:
                        current_info['aspect_ratio'] = match.group(1)
                if 'audio-track=' in line:
                    match = re.search(r'audio-track="([^"]*)"', line)
                    if match:
                        current_info['audio_track'] = match.group(1)
                if 'tvg-name=' in line:
                    match = re.search(r'tvg-name="([^"]*)"', line)
                    if match:
                        current_info['name'] = match.group(1)
            
            # now... this line should be the stream URL
            elif line and not line.startswith('#'):

                # make sure there's a name for the stream
                if 'name' in current_info:

                    # append it to the stream info
                    streams.append(StreamInfo(
                        name=current_info.get('name', 'Unknown'),
                        url=line,
                        source_id=self.config.name,
                        group=current_info.get('group', ''),
                        logo=current_info.get('logo', ''),
                        tvg_id=current_info.get('tvg_id', ''),
                        tvg_name=current_info.get('tvg_name', ''),
                        tvg_language=current_info.get('tvg_language', ''),
                        tvg_country=current_info.get('tvg_country', ''),
                        tvg_url=current_info.get('tvg_url', ''),
                        radio=current_info.get('radio', ''),
                        aspect_ratio=current_info.get('aspect_ratio', ''),
                        audio_track=current_info.get('audio_track', '')
                    ))

                # clear the current info for the next stream
                current_info = {}
        
        # return the streams
        return streams