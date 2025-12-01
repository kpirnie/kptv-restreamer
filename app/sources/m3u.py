#!/usr/bin/env python3
"""
M3U playlist source

Fetches and parses M3U/M3U8 playlists from HTTP URLs.
"""
# setup the imports
import re, logging
from typing import List
from app.models import StreamInfo
from app.sources.base import StreamSource

# setup the logger
logger = logging.getLogger(__name__)

class M3USource(StreamSource):
    
    # pre-compiled regex patterns for M3U parsing
    _GROUP_PATTERN = re.compile(r'group-title="([^"]*)"')
    _LOGO_PATTERN = re.compile(r'tvg-logo="([^"]*)"')
    _TVG_ID_PATTERN = re.compile(r'tvg-id="([^"]*)"')
    _TVG_LANGUAGE_PATTERN = re.compile(r'tvg-language="([^"]*)"')
    _TVG_COUNTRY_PATTERN = re.compile(r'tvg-country="([^"]*)"')
    _TVG_URL_PATTERN = re.compile(r'tvg-url="([^"]*)"')
    _RADIO_PATTERN = re.compile(r'radio="([^"]*)"')
    _ASPECT_RATIO_PATTERN = re.compile(r'aspect-ratio="([^"]*)"')
    _AUDIO_TRACK_PATTERN = re.compile(r'audio-track="([^"]*)"')
    _TVG_NAME_PATTERN = re.compile(r'tvg-name="([^"]*)"')

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
                
                # setup the rest of the meta data using pre-compiled patterns
                match = self._GROUP_PATTERN.search(line)
                if match:
                    current_info['group'] = match.group(1)
                
                match = self._LOGO_PATTERN.search(line)
                if match:
                    current_info['logo'] = match.group(1)
                
                match = self._TVG_ID_PATTERN.search(line)
                if match:
                    current_info['tvg_id'] = match.group(1)
                
                match = self._TVG_LANGUAGE_PATTERN.search(line)
                if match:
                    current_info['tvg_language'] = match.group(1)
                
                match = self._TVG_COUNTRY_PATTERN.search(line)
                if match:
                    current_info['tvg_country'] = match.group(1)
                
                match = self._TVG_URL_PATTERN.search(line)
                if match:
                    current_info['tvg_url'] = match.group(1)
                
                match = self._RADIO_PATTERN.search(line)
                if match:
                    current_info['radio'] = match.group(1)
                
                match = self._ASPECT_RATIO_PATTERN.search(line)
                if match:
                    current_info['aspect_ratio'] = match.group(1)
                
                match = self._AUDIO_TRACK_PATTERN.search(line)
                if match:
                    current_info['audio_track'] = match.group(1)
                
                match = self._TVG_NAME_PATTERN.search(line)
                if match:
                    current_info['name'] = match.group(1)
            
            # now... this line should be the stream URL
            elif line and not line.startswith('#'):

                # make sure there's a name for the stream
                if 'name' in current_info:

                    # Get the base name and apply prefix/suffix
                    base_name = current_info.get('name', 'Unknown')
                    display_name = f"{self.config.stream_name_prefix}{base_name}{self.config.stream_name_suffix}"

                    # append it to the stream info
                    streams.append(StreamInfo(
                        name=base_name,
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
                        audio_track=current_info.get('audio_track', ''),
                        display_name=display_name
                    ))

                # clear the current info for the next stream
                current_info = {}
        
        # return the streams
        return streams
