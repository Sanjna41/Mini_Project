from django.urls import path

from . import views

app_name = 'allocation'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('my-dashboard/', views.my_dashboard, name='my_dashboard'),
    path('accounts/password/change/', views.ProfilePasswordChangeView.as_view(), name='password_change'),
    path('availability/', views.availability_manage, name='availability'),
    path('availability/all/', views.availability_admin, name='availability_admin'),
    path('announcements/add/', views.announcement_create, name='announcement_add'),
    path('emails/', views.email_management, name='email_management'),
    path('emails/<int:notification_id>/retry/', views.email_retry, name='email_retry'),
    path('imports/', views.data_import, name='data_import'),
    path('imports/<int:batch_id>/', views.data_import, name='data_import_batch'),
    path('duties/<int:allocation_id>/replacement/', views.replacement_request, name='replacement_request'),
    path('replacement/<int:request_id>/<str:action>/', views.replacement_respond, name='replacement_respond'),

    path('faculty/', views.faculty_list, name='faculty_list'),
    path('faculty/add/', views.faculty_create, name='faculty_add'),
    path('faculty/<int:pk>/edit/', views.faculty_edit, name='faculty_edit'),
    path('subjects/', views.subject_list, name='subject_list'),
    path('subjects/add/', views.subject_create, name='subject_add'),
    path('subjects/<int:pk>/edit/', views.subject_create, name='subject_edit'),

    path('phd/', views.phd_list, name='phd_list'),
    path('phd/add/', views.phd_create, name='phd_add'),
    path('phd/<int:pk>/edit/', views.phd_edit, name='phd_edit'),

    path('classrooms/', views.classroom_list, name='classroom_list'),
    path('classrooms/add/', views.classroom_create, name='classroom_add'),
    path('classrooms/<int:pk>/edit/', views.classroom_edit, name='classroom_edit'),

    path('exams/', views.exam_schedule_list, name='exam_schedule_list'),
    path('exams/add/', views.exam_schedule_create, name='exam_schedule_add'),
    path('exams/<int:pk>/edit/', views.exam_schedule_edit, name='exam_schedule_edit'),

    path('ufm/', views.ufm_record_list, name='ufm_record_list'),
    path('ufm/add/', views.ufm_record_create, name='ufm_record_add'),

    path('seating/', views.seating_plan, name='seating_plan'),
    path('seating/generate/', views.generate_seating, name='generate_seating'),
    path('seating/sessions/add/', views.exam_session_create, name='exam_session_add'),
    path('seating/sessions/generate/', views.generate_session_seating, name='generate_session_seating'),
    path('seating/sessions/<int:session_id>/export/csv/', views.export_session_seating_csv, name='session_seating_csv'),
    path('seating/sessions/<int:session_id>/export/pdf/', views.export_session_seating_pdf, name='session_seating_pdf'),
    path('seating/search/', views.seating_search, name='seating_search'),
    path('seating/export/', views.export_seating_csv, name='export_seating_csv'),
    path('seating/<int:exam_id>/export/csv/', views.export_seating_plan_csv, name='seating_plan_csv'),
    path('seating/<int:exam_id>/export/pdf/', views.export_seating_plan_pdf, name='seating_plan_pdf'),
    path('seating/students/import/', views.import_students_csv, name='import_students_csv'),

    path('allocate/', views.run_allocation, name='run_allocation'),
    path('allocate/ajax/', views.run_allocation_ajax, name='run_allocation_ajax'),
    path('allocation/result/', views.allocation_result, name='allocation_result'),
    path('allocation/export/', views.export_allocation_csv, name='export_allocation_csv'),
    path('allocation/order/pdf/', views.duty_order_pdf, name='duty_order_pdf'),
    path('allocation/order/slip/pdf/', views.duty_slip_pdf, name='duty_slip_pdf'),
    path('allocation/order/faculty/pdf/', views.faculty_duty_details_pdf, name='faculty_duty_details_pdf'),
]

