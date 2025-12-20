# Deployment Guide - Dental Chatbot

This guide covers deploying the Dental Chatbot system to production.

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git (for cloning the repository)
- Web server (nginx, Apache, or similar) for reverse proxy (optional but recommended)
- SSL certificate for HTTPS (required for production)

## Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd dental_chatbot
```

### 2. Set Up Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your production settings
nano .env  # or use your preferred editor
```

### 3. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Edit `.env` file with your production settings:

```env
# Environment
ENV=production

# Vision API
VISION_API_HOST=0.0.0.0
VISION_API_PORT=8081

# Rasa Configuration
RASA_SERVER_URL=http://localhost:5005
RASA_ACTIONS_URL=http://localhost:5055

# CORS - IMPORTANT: Set your actual domain
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Security
DEBUG=false
SECRET_KEY=your-very-secure-secret-key-here

# Rate Limiting
RATE_LIMIT_WINDOW=60
RATE_LIMIT_MAX_REQUESTS=100
```

### 5. Start Services

#### Option A: Using Startup Scripts

**Linux/Mac:**
```bash
chmod +x start_production.sh
./start_production.sh
```

**Windows:**
```cmd
start_production.bat
```

#### Option B: Manual Start

**Terminal 1 - Vision Server:**
```bash
python run_vision_server.py --host 0.0.0.0 --port 8081
```

**Terminal 2 - Rasa Server:**
```bash
cd rasa_bot/actions
rasa run --enable-api --port 5005
```

**Terminal 3 - Rasa Actions:**
```bash
cd rasa_bot/actions
rasa run actions --port 5055
```

## Production Deployment Options

### Option 1: Systemd Service (Linux)

Create service files for each service:

**`/etc/systemd/system/dental-vision.service`:**
```ini
[Unit]
Description=Dental Chatbot Vision API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/dental_chatbot
Environment="PATH=/path/to/dental_chatbot/venv/bin"
EnvironmentFile=/path/to/dental_chatbot/.env
ExecStart=/path/to/dental_chatbot/venv/bin/python run_vision_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable dental-vision
sudo systemctl start dental-vision
sudo systemctl status dental-vision
```

### Option 2: Docker Deployment

See `docker/docker-compose.yml` for Docker configuration.

```bash
cd docker
docker-compose up -d
```

### Option 3: Reverse Proxy with Nginx

**Nginx Configuration (`/etc/nginx/sites-available/dental-chatbot`):**

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;
    
    ssl_certificate /path/to/ssl/cert.pem;
    ssl_certificate_key /path/to/ssl/key.pem;
    
    # Security headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Vision API
    location / {
        proxy_pass http://localhost:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
    
    # Rasa API (if exposing directly)
    location /rasa/ {
        proxy_pass http://localhost:5005/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site:
```bash
sudo ln -s /etc/nginx/sites-available/dental-chatbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Security Checklist

- [ ] Set `ENV=production` in `.env`
- [ ] Set `DEBUG=false` in `.env`
- [ ] Configure `ALLOWED_ORIGINS` with your actual domain
- [ ] Configure `ALLOWED_HOSTS` with your actual domain
- [ ] Set a strong `SECRET_KEY`
- [ ] Enable HTTPS/SSL
- [ ] Configure firewall rules
- [ ] Set up rate limiting
- [ ] Enable logging and monitoring
- [ ] Set up backup for database (if using)
- [ ] Review and update CORS settings
- [ ] Set up process monitoring (systemd, supervisor, etc.)

## Monitoring and Health Checks

### Health Check Endpoints

- Vision API: `http://yourdomain.com/health`
- Rasa API: `http://localhost:5005/` (if exposed)

### Logging

Logs are written to stdout/stderr. For production, redirect to log files:

```bash
python run_vision_server.py > /var/log/dental-vision.log 2>&1
```

Or use systemd journal:
```bash
sudo journalctl -u dental-vision -f
```

## Troubleshooting

### Port Already in Use

Change the port in `.env`:
```env
VISION_API_PORT=8082
```

### CORS Errors

Ensure `ALLOWED_ORIGINS` in `.env` includes your frontend domain:
```env
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

### Camera Not Working

- Ensure HTTPS is enabled (browsers require HTTPS for camera access in production)
- Check browser permissions
- Verify camera is not in use by another application

### Services Not Starting

1. Check logs for errors
2. Verify Python version (3.8+)
3. Ensure all dependencies are installed
4. Check port availability
5. Verify environment variables are set correctly

## Performance Optimization

1. **Use a reverse proxy** (nginx/Apache) for static file serving
2. **Enable gzip compression** in nginx
3. **Set up caching** for static assets
4. **Use a process manager** (systemd, supervisor, PM2)
5. **Monitor resource usage** (CPU, memory, disk)
6. **Set up load balancing** if needed

## Backup and Recovery

1. **Database backups** (if using SQLite or other database):
   ```bash
   cp appointments.db appointments.db.backup
   ```

2. **Configuration backups**:
   ```bash
   cp .env .env.backup
   ```

3. **Model backups**:
   ```bash
   tar -czf rasa_models_backup.tar.gz rasa_bot/models/
   ```

## Updates and Maintenance

1. **Pull latest changes**:
   ```bash
   git pull origin main
   ```

2. **Update dependencies**:
   ```bash
   pip install -r requirements.txt --upgrade
   ```

3. **Restart services**:
   ```bash
   sudo systemctl restart dental-vision
   ```

## Support

For issues and questions:
- Check logs: `sudo journalctl -u dental-vision -f`
- Review health endpoint: `curl http://localhost:8081/health`
- Check system resources: `htop` or `top`

