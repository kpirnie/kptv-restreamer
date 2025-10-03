import yaml
from pathlib import Path
from app.models import AppConfig, SourceConfig, FilterConfig


def load_config(config_path: str) -> AppConfig:
    """Load configuration from YAML file"""
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)
    
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
            enabled=source_data.get('enabled', True)
        ))
    
    filter_data = config_data.get('filters', {})
    filters = FilterConfig(
        include_name_patterns=filter_data.get('include_name_patterns', []),
        include_stream_patterns=filter_data.get('include_stream_patterns', []),
        exclude_name_patterns=filter_data.get('exclude_name_patterns', []),
        exclude_stream_patterns=filter_data.get('exclude_stream_patterns', [])
    )
    
    return AppConfig(
        sources=sources,
        filters=filters,
        max_total_connections=config_data.get('max_total_connections', 100),
        bind_host=config_data.get('bind_host', '0.0.0.0'),
        bind_port=config_data.get('bind_port', 8080),
        public_url=config_data.get('public_url', 'http://localhost:8080'),
        log_level=config_data.get('log_level', 'INFO')
    )