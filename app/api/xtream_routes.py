#!/usr/bin/env python3
"""
Xtream Codes API Routes Module

This module provides Xtream Codes API compatibility endpoints for the KPTV Restreamer.
It implements the standard Xtream Codes API interface for IPTV player compatibility.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import logging
from fastapi import APIRouter, HTTPException, Request, Query
from typing import Optional

# setup the logger
logger = logging.getLogger(__name__)

# setup the router
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
Check Xtream API authentication credentials

@param restreamer: StreamRestreamer Restreamer instance
@param username: str Username for authentication
@param password: str Password for authentication
@return bool: True if authentication successful or disabled
"""
def check_auth(restreamer, username: str, password: str) -> bool:
    """Check if credentials are valid"""
    if not restreamer.config.xtream_auth.enabled:
        return True
    
    return (username == restreamer.config.xtream_auth.username and 
            password == restreamer.config.xtream_auth.password)

"""
Xtream Codes API endpoint

Main API endpoint that handles all Xtream Codes API actions including
stream listings, categories, and user information.

@param request: Request FastAPI request object
@param username: str Xtream API username
@param password: str Xtream API password
@param action: str API action to perform
@return dict: Response data based on requested action
@throws HTTPException: 503 if service not initialized, 401 if auth failed
"""
@router.get("/player_api.php")
async def player_api(
    request: Request,
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    action: Optional[str] = Query(None)
):
    """Xtream Codes API endpoint"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    # Authentication check
    if not username or not password:
        raise HTTPException(status_code=401, detail="Missing credentials")
    
    if not check_auth(restreamer, username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if action == "get_live_streams":
        return await get_live_streams(restreamer)
    elif action == "get_vod_streams":
        return await get_vod_streams(restreamer)
    elif action == "get_series":
        return await get_series(restreamer)
    elif action == "get_live_categories":
        return await get_live_categories(restreamer)
    elif action == "get_vod_categories":
        return await get_vod_categories(restreamer)
    elif action == "get_series_categories":
        return await get_series_categories(restreamer)
    else:
        # Return user info when no action specified
        return get_user_info(restreamer)

"""
Get all live streams in Xtream format

Returns live streams formatted for Xtream Codes API compatibility.

@param restreamer: StreamRestreamer Restreamer instance
@return list: Formatted live streams data
"""
async def get_live_streams(restreamer):
    """Get all live streams in Xtream format"""
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    streams = []
    
    for name, stream_list in grouped_streams.items():
        primary_stream = stream_list[0]
        stream_id = await restreamer.name_mapper.get_stream_id(name)
        
        # Only include non-VOD, non-series streams
        if "(Series)" not in name and not any(ext in primary_stream.url.lower() for ext in ['.mp4', '.mkv', '.avi']):
            streams.append({
                "num": len(streams) + 1,
                "name": name,
                "stream_type": "live",
                "stream_id": stream_id,
                "stream_icon": primary_stream.logo or "",
                "epg_channel_id": "",
                "added": "0",
                "category_name": primary_stream.group or "Uncategorized",
                "category_id": str(hash(primary_stream.group or "Uncategorized") % 10000),
                "series_no": None,
                "live": "1",
                "container_extension": "ts",
                "custom_sid": "",
                "tv_archive": 0,
                "direct_source": "",
                "tv_archive_duration": 0
            })
    
    return streams

"""
Get all VOD streams in Xtream format

Returns video-on-demand streams formatted for Xtream Codes API.

@param restreamer: StreamRestreamer Restreamer instance
@return list: Formatted VOD streams data
"""
async def get_vod_streams(restreamer):
    """Get all VOD streams in Xtream format"""
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    streams = []
    
    for name, stream_list in grouped_streams.items():
        primary_stream = stream_list[0]
        stream_id = await restreamer.name_mapper.get_stream_id(name)
        
        # Only include VOD streams (mp4, mkv, etc)
        if any(ext in primary_stream.url.lower() for ext in ['.mp4', '.mkv', '.avi']) and "(Series)" not in name:
            streams.append({
                "num": len(streams) + 1,
                "name": name,
                "stream_type": "movie",
                "stream_id": stream_id,
                "stream_icon": primary_stream.logo or "",
                "rating": "0",
                "rating_5based": 0,
                "added": "0",
                "category_name": primary_stream.group or "Uncategorized",
                "category_id": str(hash(primary_stream.group or "Uncategorized") % 10000),
                "container_extension": "mp4",
                "custom_sid": "",
                "direct_source": ""
            })
    
    return streams

"""
Get all series in Xtream format

Returns series content formatted for Xtream Codes API.

@param restreamer: StreamRestreamer Restreamer instance
@return list: Formatted series data
"""
async def get_series(restreamer):
    """Get all series in Xtream format"""
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    series = []
    
    for name, stream_list in grouped_streams.items():
        primary_stream = stream_list[0]
        stream_id = await restreamer.name_mapper.get_stream_id(name)
        
        # Only include series
        if "(Series)" in name:
            clean_name = name.replace(" (Series)", "")
            series.append({
                "num": len(series) + 1,
                "name": clean_name,
                "series_id": stream_id,
                "cover": primary_stream.logo or "",
                "plot": "",
                "cast": "",
                "director": "",
                "genre": primary_stream.group or "Uncategorized",
                "releaseDate": "",
                "last_modified": "0",
                "rating": "0",
                "rating_5based": 0,
                "backdrop_path": [],
                "youtube_trailer": "",
                "episode_run_time": "0",
                "category_id": str(hash(primary_stream.group or "Uncategorized") % 10000),
                "category_name": primary_stream.group or "Uncategorized"
            })
    
    return series

"""
Get all live stream categories

Returns live stream categories for Xtream Codes API.

@param restreamer: StreamRestreamer Restreamer instance
@return list: Live stream categories
"""
async def get_live_categories(restreamer):
    """Get all live stream categories"""
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    categories = {}
    
    for name, stream_list in grouped_streams.items():
        primary_stream = stream_list[0]
        
        # Only count live streams
        if "(Series)" not in name and not any(ext in primary_stream.url.lower() for ext in ['.mp4', '.mkv', '.avi']):
            category = primary_stream.group or "Uncategorized"
            if category not in categories:
                categories[category] = {
                    "category_id": str(hash(category) % 10000),
                    "category_name": category,
                    "parent_id": 0
                }
    
    return list(categories.values())

"""
Get all VOD categories

Returns video-on-demand categories for Xtream Codes API.

@param restreamer: StreamRestreamer Restreamer instance
@return list: VOD categories
"""
async def get_vod_categories(restreamer):
    """Get all VOD categories"""
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    categories = {}
    
    for name, stream_list in grouped_streams.items():
        primary_stream = stream_list[0]
        
        # Only count VOD streams
        if any(ext in primary_stream.url.lower() for ext in ['.mp4', '.mkv', '.avi']) and "(Series)" not in name:
            category = primary_stream.group or "Uncategorized"
            if category not in categories:
                categories[category] = {
                    "category_id": str(hash(category) % 10000),
                    "category_name": category,
                    "parent_id": 0
                }
    
    return list(categories.values())

"""
Get all series categories

Returns series categories for Xtream Codes API.

@param restreamer: StreamRestreamer Restreamer instance
@return list: Series categories
"""
async def get_series_categories(restreamer):
    """Get all series categories"""
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    categories = {}
    
    for name, stream_list in grouped_streams.items():
        primary_stream = stream_list[0]
        
        # Only count series
        if "(Series)" in name:
            category = primary_stream.group or "Uncategorized"
            if category not in categories:
                categories[category] = {
                    "category_id": str(hash(category) % 10000),
                    "category_name": category,
                    "parent_id": 0
                }
    
    return list(categories.values())

"""
Get Xtream API user information

Returns user and server information for Xtream Codes API.

@param restreamer: StreamRestreamer Restreamer instance
@return dict: User and server information
"""
def get_user_info(restreamer):

    # Get exp_date from first available Xtream source
    exp_date = "9999999999"
    for source_name, source in restreamer.aggregator.sources.items():
        if hasattr(source.config, 'exp_date') and source.config.exp_date:
            exp_date = source.config.exp_date
            break

    return {
        "user_info": {
            "username": restreamer.config.xtream_auth.username,
            "password": restreamer.config.xtream_auth.password,
            "message": "Welcome to KPTV Restreamer",
            "auth": 1,
            "status": "Active",
            "exp_date": exp_date,
            "is_trial": "0",
            "active_cons": "0",
            "created_at": "0",
            "max_connections": str(restreamer.config.max_total_connections),
            "allowed_output_formats": ["ts", "m3u8", "mp4"]
        },
        "server_info": {
            "url": restreamer.config.public_url,
            "port": str(restreamer.config.bind_port),
            "https_port": "",
            "server_protocol": "http",
            "rtmp_port": "",
            "timezone": "UTC",
            "timestamp_now": 0,
            "time_now": ""
        }
    }

"""
Stream live content via Xtream format URL

Xtream-compatible endpoint for streaming live content with authentication.

@param username: str Xtream API username
@param password: str Xtream API password
@param stream_id: str Stream identifier
@param ext: str File extension (ts, m3u8, etc)
@param request: Request FastAPI request object
@return StreamingResponse: Stream content
@throws HTTPException: 503 if service not initialized, 401 if auth failed
"""
@router.get("/live/{username}/{password}/{stream_id}.{ext}")
async def stream_live(
    username: str,
    password: str,
    stream_id: str,
    ext: str,
    request: Request
):
    """Stream live content via Xtream format URL"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    if not check_auth(restreamer, username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    return await restreamer.stream_content(stream_id)

"""
Stream VOD content via Xtream format URL

Xtream-compatible endpoint for streaming video-on-demand content.

@param username: str Xtream API username
@param password: str Xtream API password
@param stream_id: str Stream identifier
@param ext: str File extension
@param request: Request FastAPI request object
@return StreamingResponse: Stream content
@throws HTTPException: 503 if service not initialized, 401 if auth failed
"""
@router.get("/movie/{username}/{password}/{stream_id}.{ext}")
async def stream_movie(
    username: str,
    password: str,
    stream_id: str,
    ext: str,
    request: Request
):
    """Stream VOD content via Xtream format URL"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    if not check_auth(restreamer, username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    return await restreamer.stream_content(stream_id)

"""
Stream series content via Xtream format URL

Xtream-compatible endpoint for streaming series content.

@param username: str Xtream API username
@param password: str Xtream API password
@param stream_id: str Stream identifier
@param ext: str File extension
@param request: Request FastAPI request object
@return StreamingResponse: Stream content
@throws HTTPException: 503 if service not initialized, 401 if auth failed
"""
@router.get("/series/{username}/{password}/{stream_id}.{ext}")
async def stream_series(
    username: str,
    password: str,
    stream_id: str,
    ext: str,
    request: Request
):
    """Stream series content via Xtream format URL"""
    restreamer = get_restreamer(request)
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    if not check_auth(restreamer, username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    return await restreamer.stream_content(stream_id)
