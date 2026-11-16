# Soko Digital (Django)

Marketplace connecting Kenyan farmers with business buyers. Payment held until delivery is confirmed.

## Run it
```bash
python -m venv venv
venv\Scripts\activate        # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
Open http://127.0.0.1:8000/

## Where we are (Module 2: Custom Front-End)
- [x] 1. Project Setup & Static/Media Config
- [x] 2. Bootstrap Setup & Basic Layout (`templates/base.html`)
- [x] 3. Structuring Your Front-End (`static/css|js|images`, `templates/`)
- [x] 4. Adding Custom CSS & JS (`static/css/style.css`, `static/js/main.js`)
- [x] 5. Creating Reusable Partials (`templates/partials/`)
- [x] 6. Mapping Views & URL Routing (`market/views.py`, `market/urls.py`)
- [ ] 7. Passing Data to Templates  <- next (move listings/prices into models)
- [ ] 8. Testing & Troubleshooting
- [ ] 9. Comparing to a ThemeWagon Theme

The listings, orders and M-Pesa flow are still the mock API inside `static/js/main.js`.
