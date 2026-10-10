from django.core.management.base import BaseCommand
from hospital.models import Department,LabTest,Ward,Bed
class Command(BaseCommand):
    help='Seed a safe empty hospital configuration (no patients or clinical events)'
    def handle(self,*args,**kwargs):
        for name in ['Emergency','Outpatient','General Medicine','Pediatrics','Laboratory','Pharmacy','Radiology','Surgery']:
            Department.objects.get_or_create(name=name)
        for code,name,sample in [('CBC','Complete Blood Count','Blood'),('GLU','Blood Glucose','Blood'),('UA','Urinalysis','Urine')]:
            LabTest.objects.get_or_create(code=code,defaults={'name':name,'sample_type':sample})
        ward,_=Ward.objects.get_or_create(name='General Ward')
        for i in range(1,9):Bed.objects.get_or_create(code=f'GW-{i:02d}',defaults={'ward':ward})
        self.stdout.write(self.style.SUCCESS('Seeded departments, test catalog, one ward, eight beds.'))
