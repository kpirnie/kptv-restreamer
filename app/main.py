#!/usr/bin/env python3
import asyncio
import logging
import argparse
from contextlib import asynccontextmanager
from typing import Optional

import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse

from app.config import load_config
from app.models import AppConfig
from app.services import (
    ConnectionManager,
    StreamCache,
    StreamNameMapper,
    StreamFilter,
    StreamAggregator
)
from app.sources import XtreamSource, M3USource

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StreamRestreamer:
    """Main application class"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.session = None
        self.connection_manager = ConnectionManager(config.max_total_connections)
        self.stream_filter = StreamFilter(config.filters)
        self.aggregator = StreamAggregator(self.stream_filter)
        self.name_mapper = StreamNameMapper()
        self.refresh_task = None
        self.stream_cache: Optional[StreamCache] = None
    
    async def initialize(self):
        """Initialize the application"""
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=30,
            sock_read=300
        )
        connector = aiohttp.TCPConnector(
            limit=100, 
            limit_per_host=20,
            keepalive_timeout=300,
            enable_cleanup_closed=True
        )
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        
        self.stream_cache = StreamCache(self.session, self.connection_manager)
        self.stream_cache.start()
        
        for source_config in self.config.sources:
            self.connection_manager.set_source_limit(
                source_config.name, source_config.max_connections)
            
            if source_config.type == 'xtream':
                source = XtreamSource(source_config, self.session)
            elif source_config.type == 'm3u':
                source = M3USource(source_config, self.session)
            else:
                logger.warning(f"Unknown source type: {source_config.type}")
                continue
            
            self.aggregator.add_source(source)
        
        self.refresh_task = asyncio.create_task(self._refresh_loop())
        await self.aggregator.refresh_all_sources()
 
    async def cleanup(self):
        """Cleanup resources"""
        if self.stream_cache:
            await self.stream_cache.stop()
        
        if self.refresh_task:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
        
        if self.session:
            await self.session.close()
    
    async def _refresh_loop(self):
        """Background task to refresh sources"""
        while True:
            try:
                await asyncio.sleep(60)
                await self.aggregator.refresh_all_sources()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in refresh loop: {e}")
        
    async def get_m3u8_playlist(self) -> str:
        """Generate M3U8 playlist of all grouped streams"""
        grouped_streams = self.aggregator.get_grouped_streams()
        
        lines = ['#EXTM3U']
        
        for name, streams in grouped_streams.items():
            primary_stream = streams[0]
            
            extinf = f'#EXTINF:-1'
            if primary_stream.group:
                extinf += f' group-title="{primary_stream.group}"'
            if primary_stream.logo:
                extinf += f' tvg-logo="{primary_stream.logo}"'
            extinf += f',{name}'
            
            lines.append(extinf)
            
            stream_id = await self.name_mapper.get_stream_id(name)
            full_url = f"{self.config.public_url.rstrip('/')}/stream/{stream_id}"
            lines.append(full_url)
        
        return '\n'.join(lines)

    async def stream_content(self, stream_id: str):
        """Stream content using cache"""
        stream_name = await self.name_mapper.get_stream_name(stream_id)
        if not stream_name:
            grouped_streams = self.aggregator.get_grouped_streams()
            for name in grouped_streams.keys():
                test_id = await self.name_mapper.get_stream_id(name)
                if test_id == stream_id:
                    stream_name = name
                    break
            
            if not stream_name:
                raise HTTPException(status_code=404, detail=f"Stream ID '{stream_id}' not found")
        
        grouped_streams = self.aggregator.get_grouped_streams()
        target_streams = grouped_streams.get(stream_name)
        
        if target_streams is None:
            stream_name_lower = stream_name.lower()
            for name, streams in grouped_streams.items():
                if name.lower() == stream_name_lower:
                    target_streams = streams
                    stream_name = name
                    break
            
            if target_streams is None:
                raise HTTPException(status_code=404, detail=f"Stream '{stream_name}' not found")
        
        logger.info(f"Request for stream '{stream_name}' with {len(target_streams)} sources")
        
        def get_source_availability(stream):
            source_id = stream.source_id
            return self.connection_manager.source_limits.get(source_id, 5) - \
                   self.connection_manager.source_connections.get(source_id, 0)
        
        indexed_streams = [(i, stream) for i, stream in enumerate(target_streams)]
        indexed_streams.sort(key=lambda x: (-get_source_availability(x[1]), x[0]))
        target_streams = [stream for _, stream in indexed_streams]
        
        last_error = None
        for stream_idx, stream in enumerate(target_streams):
            source_id = stream.source_id
            
            if not self.connection_manager.can_acquire_connection(source_id):
                logger.debug(f"Source {source_id} at connection limit, trying next")
                continue
            
            try:
                is_hls = any(ext in stream.url.lower() for ext in ['.m3u8', '.m3u'])
                
                if is_hls:
                    async with self.session.get(stream.url, timeout=30) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            return PlainTextResponse(
                                content=content, 
                                media_type="application/vnd.apple.mpegurl"
                            )
                else:
                    cached_stream = await self.stream_cache.get_or_create_stream(
                        stream_name=stream_name,
                        stream_url=stream.url,
                        source_id=source_id,
                        media_type=self._get_media_type(stream.url)
                    )
                    
                    if cached_stream.connection_error:
                        raise Exception(cached_stream.connection_error)
                    
                    consumer_id = cached_stream.get_next_consumer_id()
                    
                    logger.info(f"Serving stream '{stream_name}' from cache (consumer {consumer_id})")
                    
                    async def generate_from_cache():
                        try:
                            start_pos = cached_stream.buffer.buffer_position
                            
                            async for chunk in cached_stream.buffer.consume_from(
                                consumer_id, start_pos
                            ):
                                yield chunk
                                
                        except asyncio.CancelledError:
                            logger.info(f"Consumer {consumer_id} cancelled for '{stream_name}'")
                            raise
                        except Exception as e:
                            logger.error(f"Error in consumer {consumer_id}: {e}")
                            raise
                    
                    media_type = self._get_media_type(stream.url)
                    
                    return StreamingResponse(
                        generate_from_cache(),
                        media_type=media_type,
                        headers={
                            "Cache-Control": "no-cache, no-store, must-revalidate",
                            "Pragma": "no-cache",
                            "Expires": "0",
                            "Access-Control-Allow-Origin": "*",
                            "Access-Control-Allow-Headers": "*",
                            "Access-Control-Allow-Methods": "GET, HEAD",
                        }
                    )
            
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Source {stream_idx + 1} failed: {e}")
                continue
        
        error_msg = f"All {len(target_streams)} sources failed for '{stream_name}'. Last error: {last_error}"
        logger.error(error_msg)
        raise HTTPException(status_code=503, detail=error_msg)
    
    def _get_media_type(self, url: str) -> str:
        """Determine media type from URL"""
        url_lower = url.lower()
        if any(ext in url_lower for ext in ['.ts', '.m2ts']):
            return "video/mp2t"
        elif any(ext in url_lower for ext in ['.m3u8', '.m3u']):
            return "application/vnd.apple.mpegurl"
        elif '.mp4' in url_lower:
            return "video/mp4"
        else:
            return "video/mp2t"


def create_app(config: AppConfig) -> tuple[FastAPI, StreamRestreamer]:
    """Create FastAPI app and restreamer instance"""
    restreamer_instance = StreamRestreamer(config)
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await restreamer_instance.initialize()
        yield
        await restreamer_instance.cleanup()
    
    app = FastAPI(
        title="KPTV Restreamer",
        description="Restream HLS/TS streams from multiple sources with caching",
        version="1.0.0",
        lifespan=lifespan
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.state.restreamer = restreamer_instance
    
    from app.api.routes import router
    app.include_router(router)
    
    return app, restreamer_instance


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="HLS Stream Restreamer")
    parser.add_argument(
        "--config", 
        default="config.yaml", 
        help="Path to configuration file"
    )
    parser.add_argument("--host", help="Override bind host")
    parser.add_argument("--port", type=int, help="Override bind port")
    
    args = parser.parse_args()
    
    try:
        config = load_config(args.config)
        
        if args.host:
            config.bind_host = args.host
        if args.port:
            config.bind_port = args.port
        
        logging.getLogger().setLevel(getattr(logging, config.log_level.upper()))
        
        app, restreamer = create_app(config)
        
        logger.info(f"Starting server on {config.bind_host}:{config.bind_port}")
        logger.info("Stream caching enabled")
        uvicorn.run(
            app,
            host=config.bind_host,
            port=config.bind_port,
            log_level=config.log_level.lower()
        )
    
    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
    except Exception as e:
        logger.error(f"Failed to start: {e}")
        raise


if __name__ == "__main__":
    main()