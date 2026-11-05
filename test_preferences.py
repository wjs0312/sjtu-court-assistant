import unittest
from booking_preferences import time_groups, selection_text, site_sport, canonical_detail_url


class PreferenceTests(unittest.TestCase):
    def test_any_one_hour_is_two_independent_alternatives(self):
        self.assertEqual(time_groups('任选一段', ['20:00-21:00','21:00-22:00']), [['20:00-21:00'],['21:00-22:00']])

    def test_continuous_hours_is_one_indivisible_group(self):
        self.assertEqual(time_groups('连续两段', ['20:00-21:00','21:00-22:00']), [['20:00-21:00','21:00-22:00']])
        with self.assertRaises(ValueError): time_groups('连续两段', ['19:00-20:00','21:00-22:00'])

    def test_summary_explains_any_vs_both(self):
        self.assertIn('任选一小时', selection_text('任选一段', ['20:00-21:00','21:00-22:00']))
        self.assertIn('同一场地连续两小时', selection_text('连续两段', ['20:00-21:00','21:00-22:00']))
        self.assertIn('20:00-22:00', selection_text('连续两段', ['20:00-21:00','21:00-22:00']))

    def test_student_center_category_maps_to_real_sport_tab(self):
        self.assertEqual(site_sport('学生中心健身房'), '健身房')
        url = canonical_detail_url('https://sports.sjtu.edu.cn/pc/#/apointmentDetails/1/venue/old/0','学生中心健身房')
        self.assertIn('%25E5%2581%25A5', url)
        self.assertNotIn('/old/',url)


if __name__ == '__main__': unittest.main()
