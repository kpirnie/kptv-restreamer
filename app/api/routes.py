import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def get_restreamer(request: Request):
    """Get restreamer instance from app state"""
    return request.app.state.restreamer


@router.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "HLS Stream Restreamer API with Stream Caching",
        "version": "1.0.0",
        "endpoints": {
            "playlist": "/playlist.m3u8",
            "status": "/status",
            "streams": "/streams",
            "stream": "/stream/{stream_id}",
            "active_streams": "/active-streams",
            "cache_status": "/cache-status"
        }
    }


@router.get("/playlist.m3u8")
async def get_playlist(request: Request):
    """Get M3U8 playlist of all streams"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    playlist = await restreamer.get_m3u8_playlist()
    return PlainTextResponse(content=playlist, media_type="application/vnd.apple.mpegurl")


@router.get("/status")
async def get_status(request: Request):
    """Get service status"""
    restreamer = get_restreamer(request)
    if not restreamer:
        return {"status": "not_initialized"}
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    connection_info = await restreamer.connection_manager.get_connection_info()
    
    source_status = {}
    for source_name, source in restreamer.aggregator.sources.items():
        current_connections = connection_info["source_connections"].get(source_name, 0)
        max_connections = connection_info["source_limits"].get(source_name, 5)
        
        source_status[source_name] = {
            "enabled": source.config.enabled,
            "streams": len(source.streams),
            "connections": {
                "current": current_connections,
                "max": max_connections,
                "available": max_connections - current_connections
            },
            "last_refresh": source.last_refresh.isoformat() if source.last_refresh else None
        }
    
    return {
        "status": "running",
        "total_streams": len(grouped_streams),
        "sources": len(restreamer.aggregator.sources),
        "connections": connection_info,
        "source_details": source_status
    }


@router.get("/cache-status")
async def get_cache_status(request: Request):
    """Get stream cache status"""
    restreamer = get_restreamer(request)
    if not restreamer or not restreamer.stream_cache:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    async with restreamer.stream_cache._lock:
        cached_streams_info = []
        
        for cache_key, cached_stream in restreamer.stream_cache.active_streams.items():
            cached_streams_info.append({
                "stream_name": cached_stream.stream_name,
                "source_id": cached_stream.source_id,
                "source_url": cached_stream.stream_url,
                "is_active": cached_stream.is_active,
                "consumer_count": len(cached_stream.buffer.consumers),
                "consumers": list(cached_stream.buffer.consumers),
                "buffer_size": len(cached_stream.buffer.buffer),
                "last_access": cached_stream.last_access,
                "has_error": cached_stream.connection_error is not None,
                "error": cached_stream.connection_error
            })
    
    conn_info = await restreamer.connection_manager.get_connection_info()
    
    return {
        "total_cached_streams": len(cached_streams_info),
        "cached_streams": cached_streams_info,
        "connection_info": conn_info,
        "note": "Each cached stream represents 1 connection to the provider, served to multiple consumers"
    }


@router.get("/active-streams")
async def get_active_streams(request: Request):
    """Get information about currently active streams"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    connection_info = await restreamer.connection_manager.get_connection_info()
    active_streams = []
    
    for source_name, count in connection_info["source_connections"].items():
        if count > 0:
            active_streams.append({
                "source": source_name,
                "connections": count,
                "limit": connection_info["source_limits"].get(source_name, 5)
            })
    
    return {
        "total_active_connections": connection_info["total_connections"],
        "active_streams": active_streams
    }


@router.get("/streams")
async def get_streams(request: Request):
    """Get list of all available streams with metadata"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    streams_info = []
    
    for name, streams in grouped_streams.items():
        primary_stream = streams[0]
        stream_id = await restreamer.name_mapper.get_stream_id(name)
        
        streams_info.append({
            "id": stream_id,
            "name": name,
            "group": primary_stream.group,
            "logo": primary_stream.logo,
            "sources": len(streams),
            "source_names": [s.source_id for s in streams],
            "url": f"{restreamer.config.public_url.rstrip('/')}/stream/{stream_id}"
        })
    
    return {"streams": streams_info}


@router.get("/stream/{stream_id}")
async def stream_stream(stream_id: str, request: Request):
    """Stream a specific channel"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return await restreamer.stream_content(stream_id)


@router.get("/debug/mappings")
async def debug_mappings(request: Request):
    """Debug endpoint to see name mappings"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return await restreamer.name_mapper.get_all_mappings()


@router.get("/debug/streams/{source_name}")
async def debug_source_streams(source_name: str, request: Request):
    """Debug endpoint to see streams from a specific source"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    source = restreamer.aggregator.sources.get(source_name)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    
    return {
        "source": source_name,
        "streams": [{"name": s.name, "url": s.url} for s in source.streams.values()]
    }


@router.get("/debug/grouped-streams")
async def debug_grouped_streams(request: Request):
    """Debug endpoint to see grouped streams"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    
    result = {}
    for name, streams in grouped_streams.items():
        stream_id = await restreamer.name_mapper.get_stream_id(name)
        result[name] = {
            "id": stream_id,
            "sources": [s.source_id for s in streams],
            "urls": [s.url for s in streams]
        }
    
    return result