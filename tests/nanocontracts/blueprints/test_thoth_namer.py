from typing import Optional

from hathor.conf import HathorSettings
from hathor.crypto.util import decode_address, get_address_b58_from_bytes
from hathor.nanocontracts.types import Address, NCDepositAction, NCWithdrawalAction
from hathor.wallet import KeyPair
from tests.nanocontracts.blueprints.unittest import BlueprintTestCase

from hathor.nanocontracts.blueprints.thoth_namer import (
    ThothNamer,
    DEFAULT_MAX_PROFILE_DATA_ENTRIES,
    DEFAULT_MAX_PROFILE_KEY_LENGTH,
    DEFAULT_MAX_PROFILE_VALUE_LENGTH,
    DEFAULT_MAX_TOKEN_SYMBOL_LENGTH,
    DEFAULT_MAX_TOTAL_PROFILE_SIZE,
    DEFAULT_GRACE_PERIOD_DAYS
)

settings = HathorSettings()


class NCThothNamerBlueprintTestCase(BlueprintTestCase):

    def setUp(self):
        super().setUp()
        self.blueprint_id = self._register_blueprint_class(ThothNamer)
        self.nc_id = self.gen_random_contract_id()
        self.token_uid = self.htr_token_uid
        self.dev_key = KeyPair.create(b'123')
        assert self.dev_key.address is not None
        self.dev_address = decode_address(self.dev_key.address)
        self.registration_fee = 100

        # Default values for tests
        self.max_profile_data_entries = DEFAULT_MAX_PROFILE_DATA_ENTRIES
        self.max_profile_key_length = DEFAULT_MAX_PROFILE_KEY_LENGTH
        self.max_profile_value_length = DEFAULT_MAX_PROFILE_VALUE_LENGTH
        self.max_token_symbol_length = DEFAULT_MAX_TOKEN_SYMBOL_LENGTH
        self.max_total_profile_size = DEFAULT_MAX_TOTAL_PROFILE_SIZE
        self.grace_period_days = DEFAULT_GRACE_PERIOD_DAYS

    def get_current_timestamp(self):
        return int(self.clock.seconds())

    def initialize_contract(self, **kwargs):
        init_args = {
            "domain": "htr",
            "base_fee": self.registration_fee,
            "max_profile_data_entries": self.max_profile_data_entries,
            "max_profile_key_length": self.max_profile_key_length,
            "max_profile_value_length": self.max_profile_value_length,
            "max_token_symbol_length": self.max_token_symbol_length,
            "max_total_profile_size": self.max_total_profile_size,
            "grace_period_days": self.grace_period_days,
        }
        init_args.update(kwargs)

        context = self.create_context(address=Address(self.dev_address))
        self.runner.create_contract(
            self.nc_id,
            self.blueprint_id,
            context,
            init_args['domain'],
            init_args['base_fee'],
            init_args['max_profile_data_entries'],
            init_args['max_profile_key_length'],
            init_args['max_profile_value_length'],
            init_args['max_token_symbol_length'],
            init_args['max_total_profile_size'],
            init_args['grace_period_days'],
        )

        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_contract_domain'), init_args["domain"])
        fee_structure = self.runner.call_view_method(self.nc_id, 'get_fee_structure')
        self.assertEqual(fee_structure['base_fee'], init_args["base_fee"])
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_dev_address'), self.dev_address.hex())

    def test_basic_flow(self) -> None:
        self.initialize_contract()

        # Register a name
        name = "testname"
        owner_address, _ = self.gen_random_address_with_key()
        self._register_name(name, self.registration_fee, address=owner_address)

        # Verify name exists
        self.assertTrue(self.runner.call_view_method(self.nc_id, 'is_name_available', name, self.get_current_timestamp()) is False)
        
        # Verify owner
        self.assertEqual(
            self.runner.call_view_method(self.nc_id, 'get_name_owner', name),
            owner_address.hex()
        )

        # Change resolving address
        new_address, _ = self.gen_random_address_with_key()
        context = self.create_context(address=Address(owner_address))
        self.runner.call_public_method(self.nc_id, 'change_resolving_address', context, name, new_address)

        # Verify resolving address changed
        self.assertEqual(
            self.runner.call_view_method(self.nc_id, 'resolve_name', name, self.get_current_timestamp()),
            new_address.hex()
        )

    def test_initialize_edge_cases(self):
        """Test edge cases for contract initialization."""
        context = self.create_context(address=Address(self.dev_address))

        # Test invalid domain
        with self.assertNCFail('InvalidDomain'):
            self.runner.create_contract(self.gen_random_contract_id(), self.blueprint_id, context, "", 100,
                                        self.max_profile_data_entries, self.max_profile_key_length,
                                        self.max_profile_value_length, self.max_token_symbol_length,
                                        self.max_total_profile_size, self.grace_period_days)

        # Test invalid fee
        with self.assertNCFail('InvalidFee'):
            self.runner.create_contract(self.gen_random_contract_id(), self.blueprint_id, context, "htr", 0,
                                        self.max_profile_data_entries, self.max_profile_key_length,
                                        self.max_profile_value_length, self.max_token_symbol_length,
                                        self.max_total_profile_size, self.grace_period_days)

        # Test initialization with custom config
        custom_config = {
            "domain": "test",
            "base_fee": 200,
            "max_profile_data_entries": 10,
            "max_profile_key_length": 30,
            "max_profile_value_length": 500,
            "max_token_symbol_length": 3,
            "max_total_profile_size": 5000,
            "grace_period_days": 15
        }
        self.initialize_contract(**custom_config)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_contract_domain'), "test")
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_max_profile_data_entries'), 10)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_grace_period_days'), 15)

    def test_name_registration_edge_cases(self):
        """Test edge cases for name registration."""
        self.initialize_contract()

        # Test minimum length (3 chars)
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', "abc")
        self._register_name("abc", fee, token_symbol="ABC")
        
        # Test maximum length (80 chars)
        max_name = "a" * 80
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', max_name)
        self._register_name(max_name, fee, token_symbol="MAX")
        
        # Test valid hyphen usage
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', "valid-name-here")
        self._register_name("valid-name-here", fee, token_symbol="VLD")
        
        # Test all allowed characters
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', "test-123-name")
        self._register_name("test-123-name", fee, token_symbol="T123")
        
        # Test invalid cases
        with self.assertNCFail('InvalidNameFormat'):
            self._register_name("ab", self.registration_fee, token_symbol="AB")  # Too short
            
        with self.assertNCFail('InvalidNameFormat'):
            self._register_name("a" * 81, self.registration_fee, token_symbol="LONG")  # Too long
            
        with self.assertNCFail('InvalidNameFormat'):
            self._register_name("UPPERCASE", self.registration_fee, token_symbol="UP")  # Uppercase
            
        with self.assertNCFail('InvalidNameFormat'):
            self._register_name("invalid--name", self.registration_fee, token_symbol="INV")  # Consecutive hyphens
            
        with self.assertNCFail('InvalidNameFormat'):
            self._register_name("-start-hyphen", self.registration_fee, token_symbol="ST")  # Start hyphen
            
        with self.assertNCFail('InvalidNameFormat'):
            self._register_name("end-hyphen-", self.registration_fee, token_symbol="EN")  # End hyphen
            
        with self.assertNCFail('InvalidNameFormat'):
            self._register_name("special@chars", self.registration_fee, token_symbol="SP")  # Special chars

        # Test invalid token symbol
        with self.assertNCFail('InvalidTokenSymbol'):
            fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', "validsym")
            self._register_name("validsym", fee, token_symbol="TOOLONG")

        # Test duplicate registration
        name = "duplicate-test"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name)
        self._register_name(name, fee, token_symbol="DUP")
        with self.assertNCFail('NameAlreadyExists'):
            self._register_name(name, fee, token_symbol="DUP2")
            
        # Test fee edge cases
        with self.assertNCFail('InsufficientBalance'):
            fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', "fee-test")
            self._register_name("fee-test", fee - 1, token_symbol="FEE")  # Insufficient fee
            
        with self.assertNCFail('InvalidAmount'):
            fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', "fee-test-2")
            self._register_name("fee-test-2", fee + 1, token_symbol="FEE2")  # Non-multiple fee

    def test_name_ownership_operations(self):
        self.initialize_contract()

        # Register a name
        name = "testname"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name)
        owner_address, owner_key = self._register_name(name, fee, return_key=True)

        # Try unauthorized operations
        unauthorized_address, _ = self.gen_random_address_with_key()
        context = self.create_context(address=Address(unauthorized_address))

        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'change_resolving_address', context, name, unauthorized_address)

        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'change_name_owner', context, name, unauthorized_address)

        # Test valid ownership transfer
        new_owner, _ = self.gen_random_address_with_key()
        context = self.create_context(address=Address(owner_address))
        self.runner.call_public_method(self.nc_id, 'change_name_owner', context, name, new_owner)

        self.assertEqual(
            self.runner.call_view_method(self.nc_id, 'get_name_owner', name),
            new_owner.hex()
        )

    def test_profile_data_edge_cases(self):
        """Test edge cases for profile data operations."""
        self.initialize_contract()
        
        # Register a name and get its owner
        name = "profile-test"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name)
        owner_address = self._register_name(name, fee)
        
        context = self.create_context(address=Address(owner_address))

        # Test maximum key length
        max_key = "a" * self.max_profile_key_length
        self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, max_key, "value")
        
        # Test maximum value length
        max_value = "a" * self.max_profile_value_length
        self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", max_value)
        
        # Test maximum number of keys; 18 because we already added 2 keys just above
        for i in range(18):
            self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, f"key{i}", "value")
            
        # Test adding more than maximum keys
        with self.assertNCFail('TooManyDataKeys'):
            self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "onemore", "value")
            
        # Test invalid key format
        with self.assertNCFail('InvalidDataKey'):
            self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "invalid@key", "value")
            
        # Test too long key
        with self.assertNCFail('InvalidDataKey'):
                self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "a" * (self.max_profile_key_length + 1), "value")
            
        # Test too long value
        with self.assertNCFail('InvalidDataValue'):
            self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", "a" * (self.max_profile_value_length + 1))
            
        # Test null byte in value
        with self.assertNCFail('InvalidDataValue'):
            self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", "value\x00")
            
        # Test unauthorized update
        unauthorized_address, _ = self.gen_random_address_with_key()
        context = self.create_context(address=Address(unauthorized_address))
        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", "value")
            
        # Test deleting profile data
        context = self.create_context(address=Address(owner_address))
        self.runner.call_public_method(self.nc_id, 'delete_profile_data', context, name, "key0")
        
        # Test deleting non-existent key
        with self.assertNCFail('InvalidDataKey'):
            self.runner.call_public_method(self.nc_id, 'delete_profile_data', context, name, "nonexistent")

    def test_manager_features(self):
        """Test manager-related features."""
        self.initialize_contract()
        manager_address, _ = self.gen_random_address_with_key()

        # Register first name
        name1 = "first-name"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name1)
        self._register_name(name1, fee, address=manager_address, token_symbol="FN")

        # Verify manager has one name and it's the primary
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_manager_names', manager_address), [name1])
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_manager_primary_name', manager_address), name1)

        # Register second name
        name2 = "second-name"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name2)
        self._register_name(name2, fee, address=manager_address, token_symbol="SN")

        # Verify manager has two names and primary is still the first
        self.assertEqual(set(self.runner.call_view_method(self.nc_id, 'get_manager_names', manager_address)), {name1, name2})
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_manager_primary_name', manager_address), name1)

        # Change primary name
        context = self.create_context(address=Address(manager_address))
        self.runner.call_public_method(self.nc_id, 'change_manager_primary_name', context, name2)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_manager_primary_name', manager_address), name2)

        # Change manager address
        new_manager_address, _ = self.gen_random_address_with_key()
        self.runner.call_public_method(self.nc_id, 'change_manager_address', context, name1, new_manager_address)
        
        self.assertEqual(set(self.runner.call_view_method(self.nc_id, 'get_manager_names', manager_address)), {name2})
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_manager_names', new_manager_address), [name1])
        
        # Verify primary name of old manager is updated if it was changed
        self.runner.call_public_method(self.nc_id, 'change_manager_primary_name', context, name2) # set name2 as primary
        self.runner.call_public_method(self.nc_id, 'change_manager_address', context, name2, new_manager_address)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_manager_primary_name', manager_address), "")


    def test_dev_operations(self):
        self.initialize_contract()

        # Test fee change
        new_fee = 200
        context = self.create_context(address=Address(self.dev_address))
        self.runner.call_public_method(self.nc_id, 'change_fee', context, new_fee)
        fee_structure = self.runner.call_view_method(self.nc_id, 'get_fee_structure')
        self.assertEqual(fee_structure['base_fee'], new_fee)

        # Test unauthorized fee change
        unauthorized_address, _ = self.gen_random_address_with_key()
        context = self.create_context(address=Address(unauthorized_address))
        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'change_fee', context, 300)

        # Test dev address change
        new_dev_address, _ = self.gen_random_address_with_key()
        context = self.create_context(address=Address(self.dev_address))
        self.runner.call_public_method(self.nc_id, 'change_dev_address', context, new_dev_address)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_dev_address'), new_dev_address.hex())

    def test_dev_config_changes(self):
        """Test dev-only configuration changes."""
        self.initialize_contract()
        
        # Unauthorized user
        unauthorized_address, _ = self.gen_random_address_with_key()
        unauthorized_context = self.create_context(address=Address(unauthorized_address))
        
        # Authorized dev user
        dev_context = self.create_context(address=Address(self.dev_address))

        # Test change_fee_multiplier
        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'change_fee_multiplier', unauthorized_context, 3, 30)
        with self.assertNCFail('InvalidMultiplier'):
            self.runner.call_public_method(self.nc_id, 'change_fee_multiplier', dev_context, 3, 0)
        self.runner.call_public_method(self.nc_id, 'change_fee_multiplier', dev_context, 3, 30)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_fee_multiplier', 3), 30)

        # Test change_max_profile_data_entries
        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'change_max_profile_data_entries', unauthorized_context, 10)
        with self.assertNCFail('InvalidMaxProfileDataEntries'):
            self.runner.call_public_method(self.nc_id, 'change_max_profile_data_entries', dev_context, 0)
        self.runner.call_public_method(self.nc_id, 'change_max_profile_data_entries', dev_context, 10)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_max_profile_data_entries'), 10)

        # Test change_grace_period_days
        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'change_grace_period_days', unauthorized_context, 15)
        with self.assertNCFail('InvalidGracePeriodDays'):
            self.runner.call_public_method(self.nc_id, 'change_grace_period_days', dev_context, 0)
        self.runner.call_public_method(self.nc_id, 'change_grace_period_days', dev_context, 15)
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_grace_period_days'), 15)


    def test_nft_operations_edge_cases(self):
        """Test edge cases for NFT deposit and withdrawal operations."""
        self.initialize_contract()
        
        # Register a name and get its owner
        name = "nft-test"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name)
        owner_address = self._register_name(name, fee, token_symbol="NFT")
        
        # Get the NFT token UID
        name_data = self.runner.call_view_method(self.nc_id, 'get_name_data', name)
        token_uid = bytes.fromhex(name_data['token_uid'])

        # Withdraw the NFT first to test deposit
        context = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=1)],
            address=Address(owner_address)
        )
        self.runner.call_public_method(self.nc_id, 'withdraw_nft', context, name)
        
        # Test NFT deposit
        context = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=1)],
            address=Address(owner_address)
        )
        self.runner.call_public_method(self.nc_id, 'deposit_nft', context, name)
        
        # Test depositing again
        with self.assertNCFail('AlreadyDeposited'):
            self.runner.call_public_method(self.nc_id, 'deposit_nft', context, name)
            
        # Test wrong amount deposit
        context = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=2)],
            address=Address(owner_address)
        )
        with self.assertNCFail('InvalidAmount'):
            self.runner.call_public_method(self.nc_id, 'deposit_nft', context, name)
            
        # Test NFT withdrawal
        context = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=1)],
            address=Address(owner_address)
        )
        self.runner.call_public_method(self.nc_id, 'withdraw_nft', context, name)
        
        # Test withdrawing again
        with self.assertNCFail('NotDeposited'):
            self.runner.call_public_method(self.nc_id, 'withdraw_nft', context, name)
            
        # Test unauthorized withdrawal
        unauthorized_address, _ = self.gen_random_address_with_key()
        context = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=1)],
            address=Address(unauthorized_address)
        )
        with self.assertNCFail('NotAuthorized'):
            self.runner.call_public_method(self.nc_id, 'withdraw_nft', context, name)

    def test_expiration_edge_cases(self):
        """Test edge cases for name expiration and renewal."""
        self.initialize_contract()
        
        # Register a name
        name = "expiration-test"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name)
        owner_address, _ = self._register_name(name, fee, token_symbol="EXP", return_key=True)
        
        # Get initial expiration info
        expiration_info = self.runner.call_view_method(self.nc_id, 'get_name_expiration_info', name, self.get_current_timestamp())
        self.assertEqual(expiration_info['status'], 'active')

        # Test renewing an active name for 2 years
        two_years_fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name) * 2
        context = self.create_context(
            actions=[NCDepositAction(token_uid=self.token_uid, amount=two_years_fee)],
            address=Address(owner_address)
        )
        self.runner.call_public_method(self.nc_id, 'renew_name', context, name)
        new_expiration_info = self.runner.call_view_method(self.nc_id, 'get_name_expiration_info', name, self.get_current_timestamp())
        self.assertGreater(int(new_expiration_info['expiration_date']), int(expiration_info['expiration_date']) + 365 * 24 * 60 * 60)
        
        # Simulate time passing to expiration
        self.clock.advance(3 * 365 * 24 * 60 * 60)  # 3 years
        expiration_info = self.runner.call_view_method(self.nc_id, 'get_name_expiration_info', name, self.get_current_timestamp())
        self.assertEqual(expiration_info['status'], 'grace_period')
        
        # Test renewal during grace period
        context = self.create_context(
            actions=[NCDepositAction(token_uid=self.token_uid, amount=fee)],
            address=Address(owner_address)
        )
        self.runner.call_public_method(self.nc_id, 'renew_name', context, name)
        
        # Verify renewed status
        expiration_info = self.runner.call_view_method(self.nc_id, 'get_name_expiration_info', name, self.get_current_timestamp())
        self.assertEqual(expiration_info['status'], 'active')
        
        # Simulate time passing beyond grace period
        self.clock.advance((365 + 45) * 24 * 60 * 60)  # 1 year and 45 days
        expiration_info = self.runner.call_view_method(self.nc_id, 'get_name_expiration_info', name, self.get_current_timestamp())
        self.assertEqual(expiration_info['status'], 'available')


    def test_token_validation(self):
        self.initialize_contract()

        # Try to register with wrong token
        address_bytes, _ = self.gen_random_address_with_key()
        wrong_token = b'wrong_token'
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', "testname")
        action = NCDepositAction(token_uid=wrong_token, amount=fee)
        context = self.create_context(actions=[action], address=Address(address_bytes))
        
        with self.assertNCFail('InvalidToken'):
            self.runner.call_public_method(self.nc_id, 'create_name', context, "testname", "TEST")
    
    def test_various_view_methods(self):
        """Test various view methods for correctness."""
        self.initialize_contract(grace_period_days=30)
        name = "view-test"
        fee = self.runner.call_view_method(self.nc_id, 'calculate_fee', name)
        owner_address = self._register_name(name, fee, token_symbol="VIEW")

        # get_name_data
        name_data = self.runner.call_view_method(self.nc_id, 'get_name_data', name)
        self.assertEqual(name_data['owner_address'], owner_address.hex())
        self.assertEqual(name_data['resolving_address'], owner_address.hex())

        # get_name_expiration_date
        expiration_date = self.runner.call_view_method(self.nc_id, 'get_name_expiration_date', name)
        self.assertGreater(int(expiration_date), self.get_current_timestamp())

        # get_dev_address & get_contract_domain
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_dev_address'), self.dev_address.hex())
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'get_contract_domain'), "htr")

        # check_name_ownership
        self.assertTrue(self.runner.call_view_method(self.nc_id, 'check_name_ownership', name, owner_address, self.get_current_timestamp()))
        non_owner_address, _ = self.gen_random_address_with_key()
        self.assertFalse(self.runner.call_view_method(self.nc_id, 'check_name_ownership', name, non_owner_address, self.get_current_timestamp()))

        # check_name_status
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'check_name_status', name, self.get_current_timestamp()), 'active')
        self.clock.advance(366 * 24 * 60 * 60) # 1 year and 1 day
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'check_name_status', name, self.get_current_timestamp()), 'grace_period')
        self.clock.advance(31 * 24 * 60 * 60) # 31 days
        self.assertEqual(self.runner.call_view_method(self.nc_id, 'check_name_status', name, self.get_current_timestamp()), 'available')
        
        # get_fee_info and fee structure
        fee_info = self.runner.call_view_method(self.nc_id, 'get_fee_info', "abc")
        self.assertEqual(fee_info['total_fee'], 2000)
        fee_structure = self.runner.call_view_method(self.nc_id, 'get_fee_structure')
        self.assertEqual(fee_structure['base_fee'], self.registration_fee)

    def _register_name(self, name: str, amount: int, address: Optional[Address] = None, token_symbol: str = "TEST", return_key: bool = False):
        key = None
        if address is None:
            address_bytes, key = self.gen_random_address_with_key()
        else:
            address_bytes = address
            
        action = NCDepositAction(token_uid=self.token_uid, amount=amount)
        context = self.create_context(actions=[action], address=Address(address_bytes))
        self.runner.call_public_method(self.nc_id, 'create_name', context, name, token_symbol)
        
        if return_key:
            return address_bytes, key
        return address_bytes