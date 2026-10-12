from django.test import SimpleTestCase
from .hematology_engine import build_hematology_scene, ratio

class HematologyVisualTests(SimpleTestCase):
    def test_no_result_means_no_sickling(self):
        self.assertFalse(build_hematology_scene([])['visual']['show_sickling'])
    def test_unverified_hbs_is_ignored(self):
        scene=build_hematology_scene([{'code':'HbS','number':80,'verified':False}])
        self.assertFalse(scene['visual']['show_sickling'])
    def test_verified_hbs_activates_schematic_not_diagnosis(self):
        scene=build_hematology_scene([{'code':'HbS','number':42,'verified':True,'unit':'%'}])
        self.assertTrue(scene['visual']['show_sickling'])
        self.assertGreater(scene['visual']['sickled_cell_fraction'],0)
        self.assertNotIn('diagnosis',scene)
    def test_hbs_requires_percentage_unit(self):
        self.assertFalse(build_hematology_scene([{'code':'HbS','number':30,'verified':True,'unit':'g/dL'}])['visual']['show_sickling'])
    def test_hemoglobin_without_hbs_does_not_sickle(self):
        scene=build_hematology_scene([{'code':'HGB','number':6,'low':12,'high':16,'verified':True}])
        self.assertFalse(scene['visual']['show_sickling'])
        self.assertLess(scene['visual']['red_cell_density'],0.65)
    def test_bad_reference_range(self):
        self.assertIsNone(ratio(5,8,8))
