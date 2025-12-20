# Contributing to Dental Chatbot

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/yourusername/dental_chatbot.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Commit: `git commit -m 'Add feature'`
7. Push: `git push origin feature/your-feature-name`
8. Open a Pull Request

## Development Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest black flake8 mypy
```

## Code Style

- Follow PEP 8 for Python code
- Use type hints where possible
- Write docstrings for all functions and classes
- Keep functions focused and small
- Add comments for complex logic

## Testing

Before submitting a PR, ensure:
- All existing tests pass
- New features have tests
- Code is properly formatted
- No linter errors

## Pull Request Process

1. Update documentation if needed
2. Add tests for new features
3. Ensure all tests pass
4. Update CHANGELOG.md (if applicable)
5. Request review from maintainers

## Reporting Issues

When reporting issues, please include:
- Description of the problem
- Steps to reproduce
- Expected behavior
- Actual behavior
- Environment details (OS, Python version, etc.)
- Relevant logs or error messages

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Focus on constructive feedback
- Respect different viewpoints

Thank you for contributing! 🎉

