import unittest
from notification_binding import NotificationBinding


class BindingTests(unittest.TestCase):
    def test_successful_request_alone_does_not_claim_bound(self):
        binding = NotificationBinding(' SCT123abc ')
        binding.test_result('SCT123abc', True)
        self.assertFalse(binding.confirmed)
        self.assertTrue(binding.can_confirm)
        binding.confirm_received()
        self.assertTrue(binding.confirmed)

    def test_failure_cannot_be_confirmed(self):
        binding = NotificationBinding('SCT123abc')
        binding.test_result('SCT123abc', False)
        with self.assertRaises(ValueError): binding.confirm_received()
        self.assertFalse(binding.confirmed)

    def test_late_response_for_old_credential_is_ignored(self):
        binding = NotificationBinding('SCT123abc')
        binding.set_key('SCT456def')
        binding.test_result('SCT123abc', True)
        self.assertFalse(binding.can_confirm)

    def test_changing_key_invalidates_saved_confirmation(self):
        binding = NotificationBinding('SCT123abc')
        binding.test_result(binding.key, True); binding.confirm_received()
        saved = binding.receipt
        self.assertTrue(NotificationBinding('SCT123abc', saved).confirmed)
        self.assertFalse(NotificationBinding('SCT456def', saved).confirmed)
        binding.set_key('SCT456def')
        self.assertFalse(binding.confirmed)

    def test_invalid_key_never_reaches_network(self):
        for key in ['', 'SC3xxx', 'SCTbad/key', 'SCTbad key']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                NotificationBinding(key).validate()


if __name__ == '__main__': unittest.main()
