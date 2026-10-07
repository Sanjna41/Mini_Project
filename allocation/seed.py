from faker import Faker
from django.contrib.auth.models import User
from allocation.models import (
    Classroom,
    Faculty,
    PhDScholar,
    
)
fake = Faker("en-IN")


def run():

    # delete old data
    Faculty.objects.all().delete()
    PhDScholar.objects.all().delete()
    Classroom.objects.all().delete()
    User.objects.filter(username__startswith="faculty").delete()
    User.objects.filter(username__startswith="phd").delete()

    # create faculty
    for i in range(10):
        user = User.objects.create_user(
            username=f"faculty{i}",
            password="12345"
        )

        Faculty.objects.create (
            user=user,
            name=fake.name(),
            email=fake.email(),
            designation="PROFESSOR",
            department="CSE",
            duty_quota=5,
            is_active=True,
            must_change_password=True,
         )

    # create phd scholars
    for i in range(15):
        user = User.objects.create_user(
            username=f"phd{i}",
            password="12345",
        )

        PhDScholar.objects.create(
            user=user,
            name=fake.name(),
            max_duties=3,
            must_change_password=True,
        )

    # create classrooms
    for i in range(5):
        Classroom.objects.create(
            name=f"Room-{i+1}",
            capacity=60
        )

    print("Fake data generated successfully!")