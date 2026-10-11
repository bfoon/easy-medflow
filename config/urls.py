from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='hospital/login.html', redirect_authenticated_user=True), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('hospital.urls')),
]
handler403 = 'hospital.views.error_403'
handler404 = 'hospital.views.error_404'
admin.site.site_header = 'E-MedFlow Hospital Administration'
admin.site.site_title = 'E-MedFlow'
