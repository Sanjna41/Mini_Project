from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from allocation.forms import StaffAuthenticationForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(
            template_name='allocation/login.html',
            authentication_form=StaffAuthenticationForm,
        ),
        name='login',
    ),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('allocation.urls', namespace='allocation')),
]

