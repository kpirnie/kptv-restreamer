#!/usr/bin/env python3
"""
API Routes Module

This module defines all the REST API endpoints for the KPTV Restreamer application.
It includes endpoints for streaming, status monitoring, cache management, and debugging.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# imports
import logging
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse, Response, RedirectResponse
from typing import Optional

# setup the logger
logger = logging.getLogger(__name__)

# setup the api router
router = APIRouter()

"""
Get restreamer instance from application state

@param request: Request FastAPI request object
@return StreamRestreamer: Restreamer instance from app state
"""
def get_restreamer(request: Request):
    """Get restreamer instance from app state"""
    return request.app.state.restreamer

"""
Root endpoint with API information or Xtream API redirect

If Xtream parameters are detected, redirect to player_api.php
Otherwise provide basic API information

@return dict or RedirectResponse: API info or redirect to Xtream endpoint
"""
@router.get("/")
async def root(
    request: Request,
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    action: Optional[str] = Query(None)
):
    """Root endpoint with API information or Xtream redirect"""
    
    # Check if this is an Xtream API request
    if username is not None or password is not None or action is not None:
        # Build redirect URL with all query parameters
        query_string = str(request.url).split('?', 1)[1] if '?' in str(request.url) else ''
        redirect_url = f"/player_api.php?{query_string}"
        logger.info(f"Redirecting Xtream request from / to {redirect_url}")
        return RedirectResponse(url=redirect_url)
    
    # Otherwise return API info
    return {
        "message": "HLS Stream Restreamer API with Stream Caching",
        "version": "1.0.0",
        "endpoints": {
            "playlist": "/playlist.m3u8",
            "status": "/status",
            "streams": "/streams",
            "stream": "/stream/{stream_id}",
            "active_streams": "/active-streams",
            "cache_status": "/cache-status",
            "xtream_api": "/player_api.php"
        }
    }

"""
Get M3U8 playlist of all available streams

Returns a complete M3U8 playlist containing all aggregated streams
from all configured sources.

@param request: Request FastAPI request object
@return PlainTextResponse: M3U8 playlist content
@throws HTTPException: 503 if service not initialized
"""
@router.get("/playlist.m3u8")
async def get_playlist(request: Request):
    """Get M3U8 playlist of all streams"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    playlist = await restreamer.get_m3u8_playlist()
    return PlainTextResponse(content=playlist, media_type="application/vnd.apple.mpegurl")

"""
Get comprehensive service status information

Returns detailed status including source information, connection counts,
and stream statistics.

@param request: Request FastAPI request object
@return dict: Comprehensive service status information
"""
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

"""
Get detailed stream cache status information

Returns information about currently cached streams, including consumer counts,
buffer sizes, and error status.

@param request: Request FastAPI request object
@return dict: Cache status with detailed stream information
@throws HTTPException: 503 if service not initialized
"""
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

"""
Get information about currently active streams

Returns connection information for streams that are currently being served.

@param request: Request FastAPI request object
@return dict: Active streams and connection information
@throws HTTPException: 503 if service not initialized
"""
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

"""
Get list of all available streams with metadata

Returns detailed information about all available streams including
source information and stream URLs.

@param request: Request FastAPI request object
@return dict: List of all available streams with metadata
@throws HTTPException: 503 if service not initialized
"""
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

"""
Stream a specific channel

Initiates streaming of a specific channel by stream ID.

@param stream_id: str Unique identifier for the stream
@param request: Request FastAPI request object
@return StreamingResponse: Stream content response
@throws HTTPException: 503 if service not initialized
"""
@router.get("/stream/{stream_id}")
async def stream_stream(stream_id: str, request: Request):
    """Stream a specific channel"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return await restreamer.stream_content(stream_id)

"""
Debug endpoint to see name mappings

Returns internal name-to-ID mappings for debugging purposes.

@param request: Request FastAPI request object
@return dict: All name mappings
@throws HTTPException: 503 if service not initialized
"""
@router.get("/debug/mappings")
async def debug_mappings(request: Request):
    """Debug endpoint to see name mappings"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return await restreamer.name_mapper.get_all_mappings()

"""
Debug endpoint to see streams from a specific source

Returns streams available from a specific source for debugging.

@param source_name: str Name of the source to inspect
@param request: Request FastAPI request object
@return dict: Source streams information
@throws HTTPException: 404 if source not found, 503 if service not initialized
"""
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

"""
Debug endpoint to see grouped streams

Returns internally grouped streams for debugging aggregation.

@param request: Request FastAPI request object
@return dict: Grouped streams information
@throws HTTPException: 503 if service not initialized
"""
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

@router.get("/epg.xml")
async def get_epg(request: Request):
    """Get aggregated EPG data"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    epg_data = await restreamer.get_epg_data()
    return Response(content=epg_data, media_type="application/xml")