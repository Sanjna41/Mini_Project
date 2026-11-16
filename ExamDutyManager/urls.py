from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
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
    path('accounts/password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done'),
    ), name='password_reset'),
    path('accounts/password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
    path('', include('allocation.urls', namespace='allocation')),
]

