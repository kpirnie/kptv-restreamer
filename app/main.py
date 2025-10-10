#!/usr/bin/env python3
"""
KPTV Restreamer - Main Application Entry Point

This module serves as the main entry point for the KPTV Restreamer application.
It initializes the FastAPI server with HLS/TS stream restreaming capabilities,
including caching and multiple source support.

@package KPTV_Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""
# setup the imports necessary
import logging
import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_config
from app.models import AppConfig
from app.core import StreamRestreamer

# setup the logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

"""
Create and configure FastAPI application with restreamer instance

Initializes the StreamRestreamer core component and sets up the FastAPI
application with proper lifespan management, CORS middleware, and route registration.

@param config: AppConfig Application configuration object
@return tuple[FastAPI, StreamRestreamer] Configured app and restreamer instance
"""
def create_app(config: AppConfig) -> tuple[FastAPI, StreamRestreamer]:
    """Create FastAPI app and restreamer instance"""
    restreamer_instance = StreamRestreamer(config)
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Application lifespan context manager
        
        Handles initialization and cleanup of restreamer resources
        during application startup and shutdown.
        
        @param app: FastAPI The FastAPI application instance
        @yields Control to application runtime
        """
        await restreamer_instance.initialize()
        yield
        await restreamer_instance.cleanup()
    
    # setup the FastAPI app
    app = FastAPI(
        title="KPTV Restreamer",
        description="Restream HLS/TS streams from multiple sources with caching",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # add in the initial middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # setup the state of the app
    app.state.restreamer = restreamer_instance
    
    # import our routers
    from app.api.routes import router
    from app.api.xtream_routes import router as xtream_router
    app.include_router(router)
    app.include_router(xtream_router)
        
    # return the app and the instance
    return app, restreamer_instance

"""
Main application entry point

Parses command line arguments, loads configuration, initializes
the application, and starts the Uvicorn server.

@throws FileNotFoundError When configuration file is not found
@throws Exception For any other startup failures
"""
def main():

    # setup the argument parser
    parser = argparse.ArgumentParser(description="IPTV Stream Restreamer")
    parser.add_argument(
        "--config", 
        default="config.yaml", 
        help="Path to configuration file"
    )
    parser.add_argument("--host", help="Override bind host")
    parser.add_argument("--port", type=int, help="Override bind port")
    
    # parse the arguments
    args = parser.parse_args()
    
    # try error block
    try:

        # fire up the configuration
        config = load_config(args.config)
        
        # setup the defaults
        if args.host:
            config.bind_host = args.host
        if args.port:
            config.bind_port = args.port
        
        # sete the logging level thats configured
        logging.getLogger().setLevel(getattr(logging, config.log_level.upper()))
        
        # create our actual app
        app, restreamer = create_app(config)
        
        # some info logging
        logger.info(f"Starting server on {config.bind_host}:{config.bind_port}")
        logger.info("Stream caching enabled")

        # run the uvicorn app as it's setup
        uvicorn.run(
            app,
            host=config.bind_host,
            port=config.bind_port,
            log_level=config.log_level.lower()
        )
    
    # catch and log the config file not found
    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
    
    # catch and log other errors
    except Exception as e:
        logger.error(f"Failed to start: {e}")
        raise

"""
Direct script execution entry point
"""
if __name__ == "__main__":
    main()
    