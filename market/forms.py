from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Listing, Profile
from .utils import normalise_phone


class BootstrapMixin:
    def _style(self):
        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs["class"] = css


class LoginForm(BootstrapMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class RegisterForm(BootstrapMixin, UserCreationForm):
    role = forms.ChoiceField(choices=Profile.ROLE_CHOICES, label="I am a")
    phone = forms.CharField(max_length=20, label="Phone (M-Pesa)", help_text="e.g. 0712345678")
    location = forms.CharField(max_length=80, required=False, help_text="Where you farm or operate, e.g. Molo")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.order_fields(["role", "first_name", "last_name", "username", "email", "phone", "location", "password1", "password2"])
        self._style()

    def clean_phone(self):
        phone = normalise_phone(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("Enter a Safaricom number like 0712345678.")
        return phone

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            Profile.objects.create(
                user=user,
                role=self.cleaned_data["role"],
                phone=self.cleaned_data["phone"],
                location=self.cleaned_data["location"],
            )
        return user


class ListingEditForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Listing
        fields = ("location", "grade", "qty_kg", "price_per_kg")
        labels = {"qty_kg": "Kilograms available", "price_per_kg": "Price per kg (KES)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

    def clean_qty_kg(self):
        v = self.cleaned_data["qty_kg"]
        if v > 100000:
            raise forms.ValidationError("Maximum is 100,000 kg.")
        return v

    def clean_price_per_kg(self):
        v = self.cleaned_data["price_per_kg"]
        if not 1 <= v <= 100000:
            raise forms.ValidationError("Enter a price between 1 and 100,000.")
        return v
