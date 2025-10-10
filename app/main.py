#!/usr/bin/env python3
import logging
import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_config
from app.models import AppConfig
from app.core import StreamRestreamer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    from app.api.xtream_routes import router as xtream_router
    app.include_router(router)
    app.include_router(xtream_router)
        
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
    