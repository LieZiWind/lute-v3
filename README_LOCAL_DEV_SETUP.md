# Running a Locally Modified Lute v3 Service

This guide explains how to set up and run your locally modified version of the Lute v3 service. This is useful when you've made custom changes to the codebase and want to test or use them without relying on a published PyPI package.

## Prerequisites

1.  **Python:** Lute v3 requires Python 3.8 or newer. It's tested with versions 3.8 through 3.11. You can check your Python version with `python --version`.
2.  **pip:** Python's package installer, usually included with Python.
3.  **MeCab:** This is a morphological analyzer for Japanese text. It's required for Lute to run correctly, even if you are not actively working on Japanese language features, as some tests depend on it. Please follow the installation instructions for your operating system from the [official Lute Manual's MeCab Installation Page](https://jzohrab.github.io/lute-manual/install/mecab.html).
4.  **Git:** For cloning the repository and managing your changes.

## Setup Instructions

1.  **Clone the Repository (if you haven't already):**
    If you have an existing clone where you've made your changes, navigate to that directory. Otherwise, clone the repository:
    ```bash
    git clone <your-repository-url>
    cd lute-v3  # Or your repository's directory name
    ```

2.  **Checkout Your Development Branch:**
    Switch to the branch that contains your modifications (replace `your-feature-branch` with the actual name):
    ```bash
    git checkout your-feature-branch
    ```

3.  **Initialize Git Submodules:**
    Lute uses git submodules for language definitions.
    ```bash
    git submodule init
    git submodule update
    ```

4.  **Create and Activate a Python Virtual Environment (Recommended):**
    Using a virtual environment keeps your project dependencies isolated.
    ```bash
    # Example using Python 3.8, adjust if your Python executable is named differently (e.g., python3)
    python3.8 -m venv .venv
    ```
    Activate the virtual environment:
    *   On macOS and Linux:
        ```bash
        source .venv/bin/activate
        ```
    *   On Windows:
        ```bash
        .venv\Scriptsctivate
        ```
    Your command prompt should change to indicate that the virtual environment is active.

5.  **Install Dependencies:**
    Lute uses `flit` for dependency management.
    ```bash
    pip install flit
    flit install --only-deps --deps develop
    ```
    This installs all necessary dependencies, including those for development.

6.  **Configure `config.yml` for Development:**
    Lute's configuration is managed by `config.yml`.
    *   Copy the example configuration file:
        ```bash
        cp lute/config/config.yml.example lute/config/config.yml
        ```
    *   Edit `lute/config/config.yml` with the following settings for a safe development environment:
        *   `ENV: dev` (This is crucial to enable development mode and prevent accidental data loss if tests are run).
        *   `DBNAME: test_lute_dev.db` (The database name **must** start with `test_` to allow running tests and to distinguish it from a production database).
        *   `DATAPATH: /full/path/to/your/lute_dev_data` (Replace with an actual full path on your system where Lute can store its data, like user images and audio. Example: `/Users/yourname/Documents/lute_dev_data`).
        *   `BACKUP_PATH: /full/path/to/your/lute_dev_backup` (Replace with an actual full path for backups. Example: `/Users/yourname/Documents/lute_dev_backup`).

    **Important:** Using `ENV: dev` and a `DBNAME` prefixed with `test_` is critical to protect any production Lute data from being overwritten by development or testing activities. It's highly recommended to use a separate `DATAPATH` for your development setup.

## Running Your Local Lute Service

Once the setup is complete:

1.  **Ensure your virtual environment is activated.**
    (You should see `(.venv)` or similar at the start of your command prompt).

2.  **Start the Lute application:**
    The project uses `invoke` for task management, which provides a convenient way to start the development server.
    ```bash
    inv start
    ```
    This will typically start the server on `http://localhost:5001`.
    You can also specify a different port:
    ```bash
    inv start --port 5000
    ```
    Alternatively, you can run the application using Python's module execution:
    ```bash
    python -m lute.main
    ```
    This usually starts the server on `http://localhost:5000`.

3.  **Access Lute in Your Web Browser:**
    Open your web browser and navigate to the address shown in the terminal output from the start command (e.g., `http://localhost:5001` or `http://localhost:5000`).

You should now be able to use your locally modified version of Lute. When you're done, you can stop the server by pressing `Ctrl+C` in the terminal where it's running, and deactivate the virtual environment by typing `deactivate`.
