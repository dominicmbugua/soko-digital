def cart(request):
    """Number of different items in the cart, for the navbar badge (reads only, never creates a session)."""
    return {"cart_count": len(request.session.get("cart", {}))}
