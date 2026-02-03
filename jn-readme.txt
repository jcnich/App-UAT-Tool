Use these steps in Terminal to run the app:
1. Go to the project directory
cd /Users/john.nichols/Documents/Cursor/App-UAT-Tool
2. Activate the virtual environment
ource venv/bin/activate
source venv/bin/activate
(On Windows: venv\Scripts\activate)
3. Start the app
python app.py
Then open http://127.0.0.1:5000 in your browser.
If the venv isn’t set up yet, do this first (one time):
cd /Users/john.nichols/Documents/Cursor/App-UAT-Tool
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
After that, use steps 2 and 3 above to run the app.