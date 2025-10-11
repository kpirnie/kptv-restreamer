#!/usr/bin/env python3
"""
Stream Filter Module

This module handles stream filtering based on regex patterns for names and URLs.
It provides inclusion and exclusion filtering to control which streams are available.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import re, logging
from typing import List
from app.models import FilterConfig, StreamInfo

# setup the logger
logger = logging.getLogger(__name__)

"""
Handles stream filtering based on regex patterns

Applies include/exclude rules to stream names and URLs for content control.
"""
class StreamFilter:
    
    """
    Initialize the StreamFilter
    Sets up filter configuration and compiles regex patterns.

    @param config: FilterConfig Filter configuration with regex patterns
    """
    def __init__(self, config: FilterConfig):

        # setup the internals
        self.config = config
        self._compile_patterns()
    
    """
    Compile regex patterns
    Converts string patterns to compiled regex objects for efficient matching.

    @return None
    """
    def _compile_patterns(self):
        
        # try to compile the filters
        try:
            self.include_name_regex = [re.compile(p, re.IGNORECASE) 
                                      for p in self.config.include_name_patterns]
            self.include_stream_regex = [re.compile(p, re.IGNORECASE) 
                                        for p in self.config.include_stream_patterns]
            self.exclude_name_regex = [re.compile(p, re.IGNORECASE) 
                                      for p in self.config.exclude_name_patterns]
            self.exclude_stream_regex = [re.compile(p, re.IGNORECASE) 
                                        for p in self.config.exclude_stream_patterns]
            
        # whoops... log the error and make sure to clear out what we already have
        except re.error as e:
            logger.error(f"Invalid regex pattern: {e}")
            self.include_name_regex = []
            self.include_stream_regex = []
            self.exclude_name_regex = []
            self.exclude_stream_regex = []
    
    """
    Check if stream should be included based on filters
    Applies exclusion rules first, then inclusion rules to determine if stream passes.

    @param stream: StreamInfo Stream to evaluate
    @return bool: True if stream should be included, False otherwise
    """
    def should_include_stream(self, stream: StreamInfo) -> bool:
        
        # try the include patterns
        try:

            # for each pattern in the name excluder and return false if it exists
            for pattern in self.exclude_name_regex:
                if pattern.search(stream.name):
                    return False
            
            # for each pattern in the stream excluder and return false if it exists
            for pattern in self.exclude_stream_regex:
                if pattern.search(stream.url):
                    return False
                
            # for each pattern in the name excluder and return false if it does exists
            if self.include_name_regex:
                name_match = any(pattern.search(stream.name) 
                               for pattern in self.include_name_regex)
                if not name_match:
                    return False
            
            # for each pattern in the stream excluder and return false if it does exists
            if self.include_stream_regex:
                stream_match = any(pattern.search(stream.url) 
                                 for pattern in self.include_stream_regex)
                if not stream_match:
                    return False
            
            # default to true
            return True
        
        # whoopsie! log the exception and return false
        except Exception as e:
            logger.error(f"Error filtering stream {stream.name}: {e}")
            return False