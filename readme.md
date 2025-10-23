# HLS Stream Restreamer

A high-performance Python application for aggregating and restreaming HLS/TS streams from multiple sources with automatic failover, connection management, and unified playlist generation.

## Features

- **Multiple Source Support**: XStream Codes API and M3U playlist sources
- **Stream Aggregation**: Combines streams from multiple sources under unified channel names
- **Automatic Failover**: Seamlessly switches between sources when streams fail
- **Connection Management**: Rate limiting and connection pooling per source
- **Stream Filtering**: Regex-based filtering for including/excluding streams
- **RESTful API**: Comprehensive API for monitoring and management
- **Docker Support**: Full containerization with docker-compose
- **Real-time Monitoring**: Health checks, status endpoints, and debugging tools
- **Offline Fallback**: Serves fallback content when all sources fail

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

### Direct Installation

1. Install Python 3.12+ and dependencies:
```bash
pip install -r requirements.txt
```

2. Create configuration:
```bash
python restreamer.py --config config.yaml
# Edit the generated config.yaml file
```

3. Run the application:
```bash
python restreamer.py --config config.yaml
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
    
  - name: "backup_m3u"
    type: "m3u"
    url: "http://example.com/playlist.m3u"
    max_connections: 5
    refresh_interval: 600
    enabled: true

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
```

### Configuration Options

#### Sources
- **name**: Unique identifier for the source
- **type**: `xtream` for XStream Codes API or `m3u` for M3U playlists
- **url**: Base URL of the stream source
- **username/password**: Credentials for XStream sources
- **max_connections**: Maximum concurrent connections per source
- **refresh_interval**: How often to refresh the stream list (seconds)
- **enabled**: Whether this source is active

#### Filters
All filter patterns use Python regex syntax:
- **include_name_patterns**: Only include streams matching these name patterns
- **include_stream_patterns**: Only include streams matching these URL patterns
- **exclude_name_patterns**: Exclude streams matching these name patterns
- **exclude_stream_patterns**: Exclude streams matching these URL patterns

## API Endpoints

### Core Endpoints

- `GET /playlist.m3u8` - Get unified M3U8 playlist of all streams
- `GET /epg.xml` - Get unified XMLTV EPG from all sources
- `GET /stream/{stream_hash}` - Stream a specific channel with failover
- `GET /status` - Get service status and connection information

### Management Endpoints

- `GET /streams` - List all available streams with metadata
- `GET /active-streams` - Get information about currently active streams
- `GET /test` - Test accessibility of streams (first 10)
- `GET /debug/{stream_hash}` - Debug information for a specific stream
- `GET /direct/{stream_hash}` - Direct redirect to first source (testing)

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
    }
  }
}
```

#### Streams List
```json
{
  "streams": [
    {
      "name": "CNN HD",
      "hash": "a1b2c3d4e5f6g7h8",
      "url": "/stream/a1b2c3d4e5f6g7h8",
      "full_url": "http://localhost:8080/stream/a1b2c3d4e5f6g7h8",
      "sources": 2,
      "category": "News",
      "group": "US Channels",
      "logo": "http://example.com/cnn-logo.png"
    }
  ]
}
```

## Docker Deployment

### Building the Image

```bash
# Build locally
docker build -t kptv-restreamer .

# Or use GitHub Container Registry
docker pull ghcr.io/your-username/kptv-restreamer:latest
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
    image: ghcr.io/your-username/kptv-restreamer:latest
    container_name: kptv_restreamer
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config:/app/config:ro
    environment:
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
```

## Architecture

### Stream Aggregation
The application groups streams by name across multiple sources, enabling automatic failover. When a client requests a stream:

1. **Source Selection**: Available sources are prioritized by connection availability
2. **Connection Management**: Respects per-source connection limits
3. **Automatic Failover**: Switches to backup sources on connection failure
4. **Offline Fallback**: Serves fallback content when all sources fail

### Connection Management
- Global connection limit across all sources
- Per-source connection limits
- Real-time connection tracking
- Graceful connection cleanup

### Stream Types Supported
- **HLS (.m3u8)**: HTTP Live Streaming playlists
- **Transport Stream (.ts)**: MPEG-2 Transport Stream
- **MP4**: Direct video files
- **Generic streams**: Any streamable content

## Monitoring and Debugging

### Health Checks
Use the `/status` endpoint for service health monitoring:

```bash
curl http://localhost:8080/status
```

### Stream Testing
Test stream accessibility:

```bash
# Test first 10 streams
curl http://localhost:8080/test

# Debug specific stream
curl http://localhost:8080/debug/{stream_hash}
```

### Logs
The application provides detailed logging:
- Stream connection attempts and failures
- Failover events
- Connection management
- Configuration issues

## Performance Tuning

### Connection Limits
- Set `max_total_connections` based on your server capacity
- Adjust per-source `max_connections` based on source reliability
- Monitor connection usage via `/active-streams` endpoint

### Refresh Intervals
- Increase `refresh_interval` for stable sources to reduce API calls
- Decrease for frequently changing playlists
- Balance between freshness and performance

### Resource Usage
- The application uses async I/O for efficient connection handling
- Memory usage scales with the number of unique streams
- CPU usage is minimal during normal operation

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
python restreamer.py --config config.yaml
```

### Running Tests

```bash
# Test stream accessibility
curl http://localhost:8080/test

# Test specific endpoints
curl http://localhost:8080/status
curl http://localhost:8080/streams
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
- Use `/debug/{stream_hash}` to diagnose specific streams

**High memory usage**
- Reduce the number of sources
- Increase `refresh_interval` to cache streams longer
- Monitor via `/status` endpoint

**Connection errors**
- Verify firewall settings
- Check if sources are rate-limiting connections
- Adjust `max_connections` per source

### Debug Mode
Set `log_level: "DEBUG"` in configuration for verbose logging.

## Security Considerations

- Keep configuration files secure (contains credentials)
- Use environment variables for sensitive data in production
- Consider running behind a reverse proxy (nginx, apache)
- Regularly update dependencies

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [aiohttp](https://docs.aiohttp.org/) - Async HTTP client
- [uvicorn](https://www.uvicorn.org/) - ASGI server
- [Pydantic](https://pydantic.dev/) - Data validation