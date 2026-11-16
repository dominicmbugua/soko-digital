from django.shortcuts import render


def home(request):
    """Landing page: hero, listings, sell form, how payment works, API status.

    For now the listings still come from the mock API in static/js/main.js.
    In the 'Passing Data to Templates' lesson we replace it with real data.
    """
    return render(request, "market/home.html")
