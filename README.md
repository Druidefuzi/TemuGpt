# TemuGPT 🤖

A local AI-powered office assistant with a web-based chat interface.

## Tech Stack

- **Backend:** Python (`server.py`)
- **Frontend:** HTML, CSS, JavaScript (`frontend/`)
- **Server:** Node.js (`index.js`)
- **Database:** SQLite (`chats.db`)

## Requirements

- [Python 3.x](https://www.python.org/downloads/)
- [Node.js](https://nodejs.org/)
- [Git](https://git-scm.com/)

## Installation

**1. Clone the repository**
```bash
git clone https://github.com/Druidefuzi/TemuGpt.git
cd TemuGpt
```

**2. Run setup** *(only once)*
```bash
setup.bat
```
This will:
- Create a Python virtual environment
- Install all Python dependencies
- Install all Node.js dependencies

## Usage

```bash
start.bat
```
This starts both the Python and Node.js servers in separate windows.

## Project Structure

```
TemuGpt/
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── knowledge/
│   └── Image prompt guide.txt
├── server.py
├── index.js
├── package.json
├── requirements.txt
├── setup.bat
└── start.bat
```

## License

MIT
