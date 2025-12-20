# Dental Chatbot - Production Ready

This is a production-ready dental chatbot system with real-time facial expression and gaze detection, integrated with Rasa conversational AI.

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd dental_chatbot
cp .env.example .env
# Edit .env with your settings
```

### 2. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start Services

**Linux/Mac:**
```bash
chmod +x start_production.sh
./start_production.sh
```

**Windows:**
```cmd
start_production.bat
```

### 4. Access the Application

Open your browser and navigate to:
```
http://localhost:8081
```

## 📋 Features

- ✅ **Real-time Facial Expression Detection** - Detects 7 emotions (neutral, happy, sad, fear, anger, surprise, disgust)
- ✅ **Gaze Direction Tracking** - Monitors user attention (forward, away, down, left, right, up)
- ✅ **Emotion-Aware Chatbot** - Rasa chatbot that adapts responses based on detected emotions
- ✅ **Confidence Scoring** - Provides reliability metrics for all detections
- ✅ **Engagement Level** - Calculates user engagement based on gaze and expression
- ✅ **Production Ready** - CORS, security headers, rate limiting, error handling
- ✅ **Web Interface** - Modern, responsive web UI with camera integration

## 🏗️ Architecture

```
┌─────────────────┐
│  Web Browser    │
│  (Frontend)     │
└────────┬────────┘
         │
         ├─── POST /ingest-frame ────┐
         │                            │
         └─── GET /latest-signals ────┤
                                       │
                              ┌────────▼────────┐
                              │  Vision Server  │
                              │  (Port 8081)    │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │ Microexpression  │
                              │    Detector     │
                              └─────────────────┘
         │
         └─── POST /webhooks/rest/webhook ────┐
                                               │
                                      ┌────────▼────────┐
                                      │  Rasa Server    │
                                      │  (Port 5005)    │
                                      └────────┬────────┘
                                               │
                                      ┌────────▼────────┐
                                      │ Actions Server   │
                                      │  (Port 5055)    │
                                      └─────────────────┘
```

## 📁 Project Structure

```
dental_chatbot/
├── facial_analysis/          # Vision detection system
│   ├── microexpression_detector.py
│   └── vision_server.py
├── rasa_bot/                 # Rasa chatbot
│   ├── actions/
│   │   ├── actions.py        # Custom actions
│   │   ├── domain.yml        # Domain configuration
│   │   └── config.yml        # Rasa config
│   └── data/
│       ├── nlu.yml          # NLU training data
│       ├── stories.yml       # Conversation stories
│       └── rules.yml        # Conversation rules
├── web_integration/          # Web interface
│   ├── templates/
│   │   └── index.html
│   └── static/
│       └── webcam.js
├── .env.example              # Environment template
├── requirements.txt          # Python dependencies
├── start_production.sh       # Production startup (Linux/Mac)
├── start_production.bat      # Production startup (Windows)
└── DEPLOYMENT.md            # Detailed deployment guide
```

## 🔧 Configuration

### Environment Variables

Key configuration options in `.env`:

```env
# Environment
ENV=production

# Vision API
VISION_API_HOST=0.0.0.0
VISION_API_PORT=8081

# Rasa
RASA_SERVER_URL=http://localhost:5005
RASA_ACTIONS_URL=http://localhost:5055

# CORS (comma-separated)
ALLOWED_ORIGINS=https://yourdomain.com
ALLOWED_HOSTS=yourdomain.com

# Security
DEBUG=false
SECRET_KEY=your-secret-key

# Rate Limiting
RATE_LIMIT_WINDOW=60
RATE_LIMIT_MAX_REQUESTS=100
```

## 🔒 Security Features

- ✅ CORS middleware with configurable origins
- ✅ Security headers (X-Frame-Options, X-Content-Type-Options, etc.)
- ✅ Rate limiting per sender
- ✅ File size validation
- ✅ Trusted host middleware
- ✅ Environment-based configuration
- ✅ HTTPS support

## 📊 API Endpoints

### Vision API (Port 8081)

- `GET /` - Web interface
- `GET /health` - Health check with detector status
- `POST /ingest-frame` - Submit video frame for processing
- `GET /latest-signals` - Get latest gaze and expression signals
- `GET /stats` - Server statistics

### Rasa API (Port 5005)

- `POST /webhooks/rest/webhook` - Send messages to chatbot

## 🐳 Docker Deployment

See `docker/docker-compose.yml` for Docker configuration:

```bash
cd docker
docker-compose up -d
```

## 📖 Documentation

- **Quick Start**: `QUICK_START.md`
- **Setup Guide**: `README_SETUP.md`
- **Deployment**: `DEPLOYMENT.md`
- **Emotion System**: `EMOTION_AWARE_SYSTEM.md`

## 🧪 Testing

### Test Vision Server

```bash
curl http://localhost:8081/health
```

### Test Rasa Server

```bash
curl -X POST http://localhost:5005/webhooks/rest/webhook \
  -H "Content-Type: application/json" \
  -d '{"sender": "test", "message": "hello"}'
```

## 🛠️ Development

### Development Mode

```bash
export ENV=development
export DEBUG=true
python run_vision_server.py --reload
```

### Training Rasa Model

```bash
cd rasa_bot/actions
rasa train
```

## 📝 License

See `LICENSE` file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📞 Support

For issues and questions:
- Check logs: `tail -f /var/log/dental-vision.log`
- Health check: `curl http://localhost:8081/health`
- Review `DEPLOYMENT.md` for troubleshooting

## 🎯 Production Checklist

Before deploying to production:

- [ ] Set `ENV=production` in `.env`
- [ ] Set `DEBUG=false` in `.env`
- [ ] Configure `ALLOWED_ORIGINS` with your domain
- [ ] Configure `ALLOWED_HOSTS` with your domain
- [ ] Set a strong `SECRET_KEY`
- [ ] Enable HTTPS/SSL
- [ ] Configure firewall rules
- [ ] Set up process monitoring (systemd, supervisor, etc.)
- [ ] Configure logging
- [ ] Set up backups
- [ ] Review security settings

---

**Ready for Production** ✅

This system is production-ready with security, error handling, rate limiting, and comprehensive documentation.

