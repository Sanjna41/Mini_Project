from django.urls import path

from . import views

app_name = 'allocation'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    path('faculty/', views.faculty_list, name='faculty_list'),
    path('faculty/add/', views.faculty_create, name='faculty_add'),
    path('faculty/<int:pk>/edit/', views.faculty_edit, name='faculty_edit'),

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
]

