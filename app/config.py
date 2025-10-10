#!/usr/bin/env python3
"""
Configuration Loader Module

This module handles loading and parsing of YAML configuration files
for the KPTV Restreamer application. It converts raw YAML data into
structured configuration objects.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import yaml
from pathlib import Path
from app.models import AppConfig, SourceConfig, FilterConfig, XtreamAuthConfig

"""
Load and parse configuration from YAML file

Reads the specified YAML configuration file, validates its existence,
and converts the data into structured configuration objects for use
throughout the application.

@param config_path: str Path to the YAML configuration file
@return AppConfig: Fully populated application configuration object
@throws FileNotFoundError: When the specified config file does not exist
"""
def load_config(config_path: str) -> AppConfig:

    # load the confi file
    config_file = Path(config_path)
    
    # make sure it actually exists
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    # now open it grab the data as yaml
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)
    
    # setup and hold the sources
    sources = []
    for source_data in config_data.get('sources', []):
        sources.append(SourceConfig(
            name=source_data['name'],
            type=source_data['type'],
            url=source_data['url'],
            username=source_data.get('username'),
            password=source_data.get('password'),
            max_connections=source_data.get('max_connections', 5),
            refresh_interval=source_data.get('refresh_interval', 300),
            enabled=source_data.get('enabled', True),
            exp_date=None 
        ))
    
    # setup and hold the filters
    filter_data = config_data.get('filters', {})
    filters = FilterConfig(
        include_name_patterns=filter_data.get('include_name_patterns', []),
        include_stream_patterns=filter_data.get('include_stream_patterns', []),
        exclude_name_patterns=filter_data.get('exclude_name_patterns', []),
        exclude_stream_patterns=filter_data.get('exclude_stream_patterns', [])
    )

    # setup xtream auth config
    xtream_auth_data = config_data.get('xtream_auth', {})
    xtream_auth = XtreamAuthConfig(
        enabled=xtream_auth_data.get('enabled', False),
        username=xtream_auth_data.get('username', 'admin'),
        password=xtream_auth_data.get('password', 'admin')
    )
    
    # return the applications configuration with defaults if necessary
    return AppConfig(
        sources=sources,
        filters=filters,
        max_total_connections=config_data.get('max_total_connections', 100),
        bind_host=config_data.get('bind_host', '0.0.0.0'),
        bind_port=config_data.get('bind_port', 8080),
        public_url=config_data.get('public_url', 'http://localhost:8080'),
        log_level=config_data.get('log_level', 'INFO'),
        xtream_auth=xtream_auth
    )