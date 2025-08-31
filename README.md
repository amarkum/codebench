# CodeBench

A web-based coding platform that supports Python and Java code execution with problem-solving capabilities.

## Features

- **Multi-language Support**: Python and Java code execution
- **Problem Database**: Pre-configured coding problems with test cases
- **Real-time Testing**: Execute code against test cases
- **Modern UI**: Clean, responsive interface with Monaco editor
- **Fullscreen Mode**: Distraction-free coding experience

## Local Development

### Prerequisites

- Python 3.8+
- Java 17+ (for Java code execution)
- pip

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd codebench
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python codebench.py
```

The application will be available at `http://localhost:9001`

## Railway Deployment

This application is configured for deployment on Railway with both Python and Java runtime support.

### Deployment Steps

1. **Connect to Railway**:
   - Go to [Railway.app](https://railway.app)
   - Sign in with your GitHub account
   - Click "New Project" and select "Deploy from GitHub repo"

2. **Configure the Project**:
   - Select your CodeBench repository
   - Railway will automatically detect the configuration files:
     - `railway.json` - Specifies buildpacks for Python and Java
     - `Procfile` - Defines the start command
     - `Dockerfile` - Alternative deployment method
     - `requirements.txt` - Python dependencies

3. **Deploy**:
   - Railway will automatically build and deploy your application
   - The build process will install both Python and Java runtimes
   - Your app will be available at the provided Railway URL

### Configuration Files

- **`railway.json`**: Configures Railway to use both Python and Java buildpacks
- **`Procfile`**: Specifies the command to start the application
- **`Dockerfile`**: Alternative deployment using Docker with OpenJDK 17
- **`requirements.txt`**: Python package dependencies
- **`.dockerignore`**: Files to exclude from Docker builds

### Environment Variables

The application uses the following environment variables:

- `PORT`: Port number (default: 9001)
- `FLASK_ENV`: Flask environment (development/production)

Railway will automatically set the `PORT` environment variable.

## Architecture

### Backend
- **Flask**: Web framework
- **Python**: Primary runtime for the application
- **Java**: Secondary runtime for Java code execution

### Frontend
- **Monaco Editor**: Code editor with syntax highlighting
- **Tailwind CSS**: Styling framework
- **Vanilla JavaScript**: Client-side functionality

### Code Execution
- **Python**: Direct execution using subprocess
- **Java**: Compilation and execution using javac and java commands

## Project Structure

```
codebench/
├── codebench.py              # Main Flask application
├── codebench_test.py         # Test suite
├── codebench_problems.yml    # Problem definitions
├── requirements.txt          # Python dependencies
├── Procfile                 # Railway start command
├── railway.json             # Railway configuration
├── Dockerfile               # Docker configuration
├── .dockerignore            # Docker ignore file
├── .gitignore               # Git ignore file
└── README.md                # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally
5. Submit a pull request

## License

This project is open source and available under the MIT License.
