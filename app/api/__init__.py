#!/usr/bin/env python3
"""
API Routes Package Initialization

This package contains all API route definitions for the KPTV Restreamer application.
It exports the main router instance for inclusion in the FastAPI application.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""
from .routes import router

# hold the necessary modules
__all__ = ["router"]