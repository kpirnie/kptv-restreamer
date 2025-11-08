# HLS Stream Restreamer

A high-performance Python application for aggregating and restreaming HLS/TS streams from multiple sources with automatic failover, connection management, and unified playlist generation.

## Features

- **Multiple Source Support**: XStream Codes API and M3U playlist sources
- **Stream Aggregation**: Combines streams from multiple sources under unified channel names
- **Automatic Failover**: Seamlessly switches between sources when streams fail
- **Connection Management**: Rate limiting and connection pooling per source
- **Stream Filtering**: Regex-based filtering for including/excluding streams
- **Stream Caching**: Single upstream connection per stream, served to multiple clients
- **Per-Source Branding**: Customizable prefix/suffix for stream names from each source
- **RESTful API**: Comprehensive API for monitoring and management
- **Xtream Codes API**: Full Xtream Codes API compatibility for IPTV apps
- **Docker Support**: Full containerization with docker-compose
- **Real-time Monitoring**: Health checks, status endpoints, and debugging tools
- **EPG Support**: Aggregated XMLTV EPG data from all sources

## Quick Start

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone <repository-url>
cd kptv-restreamer
```

2. Create your configuration:
```bash
mkdir config
cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml with your stream sources
```

3. Run with Docker Compose:
```bash
docker-compose up -d
```

4. Access your streams:
- Playlist: `http://localhost:9000/playlist.m3u8`
- Status: `http://localhost:9000/status`
- EPG: `http://localhost:9000/epg.xml`

### Direct Installation

1. Install Python 3.12+ and dependencies:
```bash
pip install -r requirements.txt
```

2. Create configuration:
```bash
mkdir config
# Create config/config.yaml based on the example below
```

3. Run the application:
```bash
python -m app.main --config config/config.yaml
```

## Configuration

The application uses a YAML configuration file. Here's a complete example:

```yaml
# Stream sources configuration
sources:
  - name: "primary_xtream"
    type: "xtream"
    url: "http://your-xtream-server.com:8080"
    username: "your_username"
    password: "your_password"
    max_connections: 10
    refresh_interval: 300
    enabled: true
    stream_name_prefix: "[XTream] "
    stream_name_suffix: " HD"
    
  - name: "backup_m3u"
    type: "m3u"
    url: "http://example.com/playlist.m3u"
    max_connections: 5
    refresh_interval: 600
    enabled: true
    stream_name_prefix: "[M3U] "
    stream_name_suffix: ""

# Stream filtering (all patterns are regex)
filters:
  include_name_patterns:
    - ".*HD.*"
    - ".*FHD.*"
  include_stream_patterns: []
  exclude_name_patterns:
    - ".*test.*"
    - ".*XXX.*"
  exclude_stream_patterns:
    - ".*adult.*"

# Connection management
max_total_connections: 100
bind_host: "0.0.0.0"
bind_port: 8080
public_url: "http://localhost:8080"
log_level: "INFO"

# Xtream Codes API compatibility (optional)
xtream_auth:
  enabled: false
  username: "admin"
  password: "admin"
```

### Configuration Options

#### Sources
- **name**: Unique identifier for the source
- **type**: `xtream` for XStream Codes API or `m3u` for M3U playlists
- **url**: Base URL of the stream source
- **username/password**: Credentials for XStream sources (required for `xtream` type)
- **max_connections**: Maximum concurrent connections per source
- **refresh_interval**: How often to refresh the stream list (seconds)
- **enabled**: Whether this source is active
- **stream_name_prefix**: Text to prepend to all stream names from this source (optional)
- **stream_name_suffix**: Text to append to all stream names from this source (optional)

#### Filters
All filter patterns use Python regex syntax:
- **include_name_patterns**: Only include streams matching these name patterns
- **include_stream_patterns**: Only include streams matching these URL patterns
- **exclude_name_patterns**: Exclude streams matching these name patterns
- **exclude_stream_patterns**: Exclude streams matching these URL patterns

#### Xtream API Authentication
- **enabled**: Enable/disable Xtream API authentication
- **username**: Username for Xtream API access
- **password**: Password for Xtream API access

## API Endpoints

### Core Endpoints

- `GET /` - API information and available endpoints
- `GET /playlist.m3u8` - Get unified M3U8 playlist of all streams
- `GET /epg.xml` - Get unified XMLTV EPG from all sources
- `GET /stream/{stream_id}` - Stream a specific channel with failover
- `GET /status` - Get service status and connection information

### Management Endpoints

- `GET /streams` - List all available streams with metadata
- `GET /active-streams` - Get information about currently active streams
- `GET /cache-status` - Get detailed stream cache information

### Debug Endpoints

- `GET /debug/mappings` - View name-to-ID mappings
- `GET /debug/streams/{source_name}` - View streams from specific source
- `GET /debug/grouped-streams` - View internally grouped streams

### Xtream Codes API Endpoints

The restreamer provides full Xtream Codes API compatibility:

- `GET /player_api.php` - Main Xtream API endpoint
  - `?action=get_live_streams` - Get all live streams
  - `?action=get_vod_streams` - Get all VOD content
  - `?action=get_series` - Get all series
  - `?action=get_live_categories` - Get live stream categories
  - `?action=get_vod_categories` - Get VOD categories
  - `?action=get_series_categories` - Get series categories
  - No action - Get user info

- `GET /live/{username}/{password}/{stream_id}.ts` - Stream live content
- `GET /movie/{username}/{password}/{stream_id}.mp4` - Stream VOD content
- `GET /series/{username}/{password}/{stream_id}.ts` - Stream series content

### Response Examples

#### Status Endpoint
```json
{
  "status": "running",
  "total_streams": 1250,
  "sources": 2,
  "connections": {
    "total_connections": 15,
    "max_total": 100,
    "available_total": 85,
    "source_connections": {
      "primary_xtream": 12,
      "backup_m3u": 3
    },
    "source_limits": {
      "primary_xtream": 10,
      "backup_m3u": 5
    }
  },
  "source_details": {
    "primary_xtream": {
      "enabled": true,
      "streams": 800,
      "connections": {
        "current": 12,
        "max": 10,
        "available": -2
      },
      "last_refresh": "2025-01-15T10:30:00"
    }
  }
}
```

#### Streams List
```json
{
  "streams": [
    {
      "id": "CNNHDNews",
      "name": "CNN HD News",
      "group": "News",
      "logo": "http://example.com/cnn-logo.png",
      "sources": 2,
      "source_names": ["primary_xtream", "backup_m3u"],
      "url": "http://localhost:8080/stream/CNNHDNews"
    }
  ]
}
```

#### Cache Status
```json
{
  "total_cached_streams": 5,
  "cached_streams": [
    {
      "stream_name": "CNN HD",
      "source_id": "primary_xtream",
      "source_url": "http://provider.com/stream.ts",
      "is_active": true,
      "consumer_count": 3,
      "consumers": [0, 1, 2],
      "buffer_size": 250,
      "last_access": 1642248000.0,
      "has_error": false,
      "error": null
    }
  ],
  "connection_info": {
    "total_connections": 5,
    "max_total": 100
  },
  "note": "Each cached stream represents 1 connection to the provider, served to multiple consumers"
}
```

## Docker Deployment

### Building the Image

```bash
# Build locally
docker build -t kptv-restreamer .

# Or use GitHub Container Registry
docker pull ghcr.io/kpirnie/kptv-restreamer:latest
```

### Environment Variables

The Docker container supports these environment variables:

- `PYTHONUNBUFFERED=1` - Disable Python output buffering
- `PYTHONDONTWRITEBYTECODE=1` - Don't generate .pyc files

### Volume Mounts

- `/app/config` - Configuration directory (mount your config files here)

### Docker Compose

```yaml
services:
  kptv-restreamer:
    image: ghcr.io/kpirnie/kptv-restreamer:latest
    container_name: kptv_restreamer
    hostname: kptv_restreamer
    restart: unless-stopped
    ports:
      - "9000:8080"
    volumes:
      - ./config:/app/config:ro
    environment:
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
```

## Architecture

### Stream Caching
The application implements intelligent stream caching to optimize connections:

1. **Single Upstream Connection**: Only one connection per stream to the provider
2. **Multiple Consumers**: Multiple clients can watch the same stream
3. **Buffer Management**: In-memory circular buffer with configurable size
4. **Automatic Cleanup**: Stale streams are automatically cleaned up

### Stream Aggregation
The application groups streams by name across multiple sources, enabling automatic failover. When a client requests a stream:

1. **Source Selection**: Available sources are prioritized by connection availability
2. **Connection Management**: Respects per-source connection limits
3. **Automatic Failover**: Switches to backup sources on connection failure
4. **Cache Reuse**: If stream is already cached, serves from cache regardless of source

### Connection Management
- Global connection limit across all sources
- Per-source connection limits
- Real-time connection tracking
- Graceful connection cleanup
- API call rate limiting per source

### Stream Types Supported
- **HLS (.m3u8)**: HTTP Live Streaming playlists
- **Transport Stream (.ts)**: MPEG-2 Transport Stream
- **MP4**: Direct video files (VOD)
- **Generic streams**: Any streamable content

## Monitoring and Debugging

### Health Checks
Use the `/status` endpoint for service health monitoring:

```bash
curl http://localhost:8080/status
```

### Cache Status
Monitor active cached streams and consumer counts:

```bash
curl http://localhost:8080/cache-status
```

### Stream Debugging
Debug specific stream mappings and sources:

```bash
# View all name mappings
curl http://localhost:8080/debug/mappings

# View streams from specific source
curl http://localhost:8080/debug/streams/primary_xtream

# View grouped streams
curl http://localhost:8080/debug/grouped-streams
```

### Logs
The application provides detailed logging:
- Stream cache creation and cleanup
- Connection acquisition and release
- Failover events
- Consumer connections and disconnections
- Configuration issues

## Performance Tuning

### Connection Limits
- Set `max_total_connections` based on your server capacity
- Adjust per-source `max_connections` based on source reliability
- Monitor connection usage via `/active-streams` and `/cache-status` endpoints

### Refresh Intervals
- Increase `refresh_interval` for stable sources to reduce API calls
- Decrease for frequently changing playlists
- Balance between freshness and performance

### Cache Management
- Streams are automatically cached when first requested
- Cached streams remain active while consumers are connected
- Stale streams (no consumers for 60 seconds) are automatically cleaned up
- Buffer size is fixed at 1000 chunks per stream

### Resource Usage
- The application uses async I/O for efficient connection handling
- Memory usage scales with the number of actively cached streams
- Each cached stream maintains a circular buffer of recent chunks
- CPU usage is minimal during normal operation

## Stream Name Branding

You can customize how stream names appear in playlists by using the `stream_name_prefix` and `stream_name_suffix` options on a per-source basis. This is useful for:

- **Source Identification**: Prefix streams with source name (e.g., "[Provider A] CNN")
- **Quality Indicators**: Add quality suffixes (e.g., "ESPN HD")
- **Branding**: Apply consistent branding across streams from a source
- **Testing**: Easily identify which source streams come from during testing

Example:
```yaml
sources:
  - name: "provider_a"
    type: "xtream"
    url: "http://provider-a.com:8080"
    stream_name_prefix: "[Provider A] "
    stream_name_suffix: ""
    
  - name: "provider_b"
    type: "m3u"
    url: "http://provider-b.com/playlist.m3u"
    stream_name_prefix: ""
    stream_name_suffix: " [Backup]"
```

This would produce stream names like:
- From provider_a: `[Provider A] CNN`, `[Provider A] ESPN`
- From provider_b: `CNN [Backup]`, `ESPN [Backup]`

## Development

### Setting Up Development Environment

```bash
# Clone repository
git clone <repository-url>
cd kptv-restreamer

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Run in development mode
python -m app.main --config config/config.yaml
```

### Project Structure

```
kptv-restreamer/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Application entry point
│   ├── config.py              # Configuration loader
│   ├── api/                   # API route definitions
│   │   ├── routes.py          # Core API endpoints
│   │   └── xtream_routes.py   # Xtream API compatibility
│   ├── core/                  # Core application logic
│   │   └── restreamer.py      # Main orchestrator
│   ├── models/                # Data models
│   │   └── stream.py          # Stream and config models
│   ├── services/              # Service layer
│   │   ├── connection_manager.py
│   │   ├── stream_cache.py
│   │   ├── stream_aggregator.py
│   │   ├── stream_filter.py
│   │   ├── stream_mapper.py
│   │   └── stream_service.py
│   └── sources/               # Stream source implementations
│       ├── base.py            # Base source class
│       ├── xtream.py          # Xtream Codes API
│       └── m3u.py             # M3U playlist parser
├── config/                    # Configuration files
├── Dockerfile
├── docker-compose-example.yaml
├── requirements.txt
└── readme.md
```

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Commit your changes: `git commit -am 'Add feature'`
5. Push to the branch: `git push origin feature-name`
6. Submit a pull request

## Troubleshooting

### Common Issues

**"Service not initialized" errors**
- Check if the configuration file exists and is valid
- Verify source credentials and URLs
- Check logs for initialization errors

**Streams not loading**
- Verify source URLs are accessible
- Check connection limits aren't exceeded
- Use `/debug/streams/{source_name}` to diagnose specific sources
- Check `/cache-status` to see if streams are cached and active

**High memory usage**
- Reduce the number of sources
- Increase `refresh_interval` to cache streams longer
- Monitor via `/cache-status` to see active cached streams
- Each cached stream maintains a buffer - many concurrent streams = more memory

**Connection errors**
- Verify firewall settings
- Check if sources are rate-limiting connections
- Adjust `max_connections` per source
- Monitor connection usage via `/status` endpoint

**Cache not working**
- Check `/cache-status` to verify streams are being cached
- Look for error messages in cached stream entries
- Verify source connections are successful
- Check logs for cache-related errors

### Debug Mode
Set `log_level: "DEBUG"` in configuration for verbose logging.

## Security Considerations

- Keep configuration files secure (contains credentials)
- Use environment variables for sensitive data in production
- Consider running behind a reverse proxy (nginx, apache)
- Regularly update dependencies
- Use Xtream API authentication when exposing to external networks
- Review and restrict network access to the service

## License

MIT License - See LICENSE file for details

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [aiohttp](https://docs.aiohttp.org/) - Async HTTP client
- [uvicorn](https://www.uvicorn.org/) - ASGI server
- [PyYAML](https://pyyaml.org/) - YAML parser
- [Pydantic](https://pydantic.dev/) - Data validation

