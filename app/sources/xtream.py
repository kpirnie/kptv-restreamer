import logging
from typing import List
from app.models import StreamInfo
from app.sources.base import StreamSource

logger = logging.getLogger(__name__)


class XtreamSource(StreamSource):
    """XStream Codes API source"""
    
    async def _fetch_streams(self) -> List[StreamInfo]:
        streams = []
        
        live_url = f"{self.config.url}/player_api.php"
        
        # Get user info to retrieve exp_date
        try:
            user_params = {
                'username': self.config.username,
                'password': self.config.password
            }
            async with self.session.get(live_url, params=user_params) as resp:
                if resp.status == 200:
                    user_data = await resp.json()
                    if 'user_info' in user_data:
                        self.config.exp_date = user_data['user_info'].get('exp_date', '9999999999')
        except Exception as e:
            logger.error(f"Failed to fetch user info: {e}")
            self.config.exp_date = '9999999999'
        
        params = {
            'username': self.config.username,
            'password': self.config.password,
            'action': 'get_live_streams'
        }
        
        try:
            async with self.session.get(live_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for stream in data:
                        stream_url = f"{self.config.url}/live/{self.config.username}/{self.config.password}/{stream.get('stream_id', '')}.ts"
                        
                        streams.append(StreamInfo(
                            name=stream.get('name', ''),
                            url=stream_url,
                            source_id=self.config.name,
                            category=stream.get('category_name', ''),
                            logo=stream.get('stream_icon', ''),
                            stream_id=str(stream.get('stream_id', ''))
                        ))
        except Exception as e:
            logger.error(f"Failed to fetch live streams: {e}")
        
        try:
            vod_params = params.copy()
            vod_params['action'] = 'get_vod_streams'
            
            async with self.session.get(live_url, params=vod_params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for stream in data:
                        stream_url = f"{self.config.url}/movie/{self.config.username}/{self.config.password}/{stream.get('stream_id', '')}.mp4"
                        
                        streams.append(StreamInfo(
                            name=stream.get('name', ''),
                            url=stream_url,
                            source_id=self.config.name,
                            category=stream.get('category_name', ''),
                            logo=stream.get('stream_icon', ''),
                            stream_id=str(stream.get('stream_id', ''))
                        ))
        except Exception as e:
            logger.error(f"Failed to fetch VOD streams: {e}")
        
        try:
            series_params = params.copy()
            series_params['action'] = 'get_series'
            
            async with self.session.get(live_url, params=series_params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for series in data:
                        series_id = series.get('series_id', '')
                        series_name = series.get('name', '')
                        
                        streams.append(StreamInfo(
                            name=f"{series_name} (Series)",
                            url=f"{self.config.url}/series/{self.config.username}/{self.config.password}/{series_id}.ts",
                            source_id=self.config.name,
                            category=series.get('category_name', ''),
                            logo=series.get('cover', ''),
                            stream_id=str(series_id)
                        ))
        except Exception as e:
            logger.error(f"Failed to fetch series: {e}")
        
        return streams
