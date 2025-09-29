import os
from typing import Optional
from hathor.conf import HathorSettings
from hathor.crypto.util import decode_address, get_address_b58_from_bytes
from hathor.nanocontracts.storage import NCMemoryStorageFactory
from hathor.nanocontracts.storage.backends import MemoryNodeTrieStore
from hathor.nanocontracts.storage.patricia_trie import PatriciaTrie
from hathor.nanocontracts.context import Context
from hathor.nanocontracts.types import Address, Amount, ContractId, NCAction, NCActionType
from hathor.wallet import KeyPair
from tests.nanocontracts.blueprints.unittest import BlueprintTestCase
from tests.nanocontracts.utils import TestRunner

from hathor.nanocontracts.blueprints.thoth_namer import (
    ThothNamer,
    NameNotFound,
    NameAlreadyExists,
    NotAuthorized,
    InvalidNameFormat,
    WithdrawalNotAllowed,
    DepositNotAllowed,
    InsufficientBalance,
    InvalidFee,
    InvalidDomain,
    TooManyActions,
    InvalidToken,
    InvalidAmount,
    TooManyDataKeys,
    InvalidDataKey,
    InvalidDataValue,
    NameExpired,
    NameInGracePeriod
)

settings = HathorSettings()

class NCThothNamerBlueprintTestCase(BlueprintTestCase):
    use_memory_storage = True

    def setUp(self):
        super().setUp()
        self.manager = self.create_peer('testnet')
        self.token_uid = settings.HATHOR_TOKEN_UID
        self.nc_id = ContractId(b'1' * 32)

        nc_storage_factory = NCMemoryStorageFactory()
        store = MemoryNodeTrieStore()
        block_trie = PatriciaTrie(store)
        self.runner = TestRunner(self.manager.tx_storage, nc_storage_factory, block_trie)
        self.nc_storage = self.runner.get_storage(self.nc_id)

    def get_current_timestamp(self):
        return int(self.clock.seconds())

    def initialize_contract(self):
        runner = self.runner
        storage = self.nc_storage

        self.dev_key = KeyPair.create(b'123')
        assert self.dev_key.address is not None
        self.dev_address = decode_address(self.dev_key.address)
        self.registration_fee = 100

        runner.register_contract(ThothNamer, self.nc_id)

        tx = self._get_any_tx()
        context = Context([], tx, self.dev_address, timestamp=self.get_current_timestamp())
        runner.call_public_method(self.nc_id, 'initialize', context, "htr", self.registration_fee)
        
        self.assertEqual(storage.get('domain'), "htr")
        self.assertEqual(storage.get('fee'), self.registration_fee)
        self.assertEqual(storage.get('dev_address'), self.dev_address)

    def test_basic_flow(self) -> None:
        self.initialize_contract()
        runner = self.runner

        # Register a name
        name = "testname"
        owner_address = self._register_name(name, self.registration_fee)

        # Verify name exists
        self.assertTrue(runner.call_view_method(self.nc_id, 'check_name_existence', name))
        
        # Verify owner
        self.assertEqual(
            runner.call_view_method(self.nc_id, 'get_name_owner', name),
            owner_address
        )

        # Change resolving address
        new_address, _ = self._get_any_address()
        tx = self._get_any_tx()
        context = Context([], tx, owner_address, timestamp=self.get_current_timestamp())
        runner.call_public_method(self.nc_id, 'change_resolving_address', context, name, new_address)

        # Verify resolving address changed
        self.assertEqual(
            runner.call_view_method(self.nc_id, 'resolve_name', name),
            get_address_b58_from_bytes(new_address)
        )

    def test_name_registration_edge_cases(self):
        """Test edge cases for name registration."""
        self.initialize_contract()

        # Test minimum length (3 chars)
        self._register_name("abc", self.registration_fee)
        
        # Test maximum length (80 chars)
        max_name = "a" * 80
        self._register_name(max_name, self.registration_fee)
        
        # Test valid hyphen usage
        self._register_name("valid-name-here", self.registration_fee)
        
        # Test all allowed characters
        self._register_name("test-123-name", self.registration_fee)
        
        # Test invalid cases
        with self.assertRaises(InvalidNameFormat):
            self._register_name("ab", self.registration_fee)  # Too short
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("a" * 81, self.registration_fee)  # Too long
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("UPPERCASE", self.registration_fee)  # Uppercase
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("invalid--name", self.registration_fee)  # Consecutive hyphens
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("-start-hyphen", self.registration_fee)  # Start hyphen
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("end-hyphen-", self.registration_fee)  # End hyphen
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("special@chars", self.registration_fee)  # Special chars
            
        # Test duplicate registration
        name = "duplicate-test"
        self._register_name(name, self.registration_fee)
        with self.assertRaises(NameAlreadyExists):
            self._register_name(name, self.registration_fee)
            
        # Test fee edge cases
        with self.assertRaises(InsufficientBalance):
            self._register_name("fee-test", self.registration_fee - 1)  # Insufficient fee
            
        with self.assertRaises(InvalidAmount):
            self._register_name("fee-test", self.registration_fee + 1)  # Non-multiple fee

    def test_name_ownership_operations(self):
        self.initialize_contract()
        runner = self.runner

        # Register a name
        name = "testname"
        owner_address = self._register_name(name, self.registration_fee)

        # Try unauthorized operations
        unauthorized_address, _ = self._get_any_address()
        tx = self._get_any_tx()
        context = Context([], tx, unauthorized_address, timestamp=self.get_current_timestamp())

        with self.assertRaises(NotAuthorized):
            runner.call_public_method(self.nc_id, 'change_resolving_address', context, name, unauthorized_address)

        with self.assertRaises(NotAuthorized):
            runner.call_public_method(self.nc_id, 'change_name_owner', context, name, unauthorized_address)

        # Test valid ownership transfer
        new_owner, _ = self._get_any_address()
        context = Context([], tx, owner_address, timestamp=self.get_current_timestamp())
        runner.call_public_method(self.nc_id, 'change_name_owner', context, name, new_owner)

        self.assertEqual(
            runner.call_view_method(self.nc_id, 'get_name_owner', name),
            new_owner
        )

    def test_profile_data_edge_cases(self):
        """Test edge cases for profile data operations."""
        self.initialize_contract()
        runner = self.runner
        
        # Register a name and get its owner
        name = "profile-test"
        owner_address = self._register_name(name, self.registration_fee)
        tx = self._get_any_tx()
        
        # Test maximum key length
        max_key = "a" * 50
        context = Context([], tx, owner_address, timestamp=self.get_current_timestamp())
        runner.call_public_method(self.nc_id, 'update_profile_data', context, name, max_key, "value")
        
        # Test maximum value length
        max_value = "a" * 1000
        runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", max_value)
        
        # Test maximum number of keys
        for i in range(20):
            runner.call_public_method(self.nc_id, 'update_profile_data', context, name, f"key{i}", "value")
            
        # Test adding more than maximum keys
        with self.assertRaises(TooManyDataKeys):
            runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "onemore", "value")
            
        # Test invalid key format
        with self.assertRaises(InvalidDataKey):
            runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "invalid@key", "value")
            
        # Test too long key
        with self.assertRaises(InvalidDataKey):
            runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "a" * 51, "value")
            
        # Test too long value
        with self.assertRaises(InvalidDataValue):
            runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", "a" * 1001)
            
        # Test null byte in value
        with self.assertRaises(InvalidDataValue):
            runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", "value\x00")
            
        # Test unauthorized update
        unauthorized_address, _ = self._get_any_address()
        context = Context([], tx, unauthorized_address, timestamp=self.get_current_timestamp())
        with self.assertRaises(NotAuthorized):
            runner.call_public_method(self.nc_id, 'update_profile_data', context, name, "key", "value")
            
        # Test deleting profile data
        context = Context([], tx, owner_address, timestamp=self.get_current_timestamp())
        runner.call_public_method(self.nc_id, 'delete_profile_data', context, name, "key0")
        
        # Test deleting non-existent key
        with self.assertRaises(InvalidDataKey):
            runner.call_public_method(self.nc_id, 'delete_profile_data', context, name, "nonexistent")

    def test_dev_operations(self):
        self.initialize_contract()
        runner = self.runner

        # Test fee change
        new_fee = 200
        tx = self._get_any_tx()
        context = Context([], tx, self.dev_address, timestamp=self.get_current_timestamp())
        runner.call_public_method(self.nc_id, 'change_fee', context, new_fee)
        self.assertEqual(self.nc_storage.get('fee'), new_fee)

        # Test unauthorized fee change
        unauthorized_address, _ = self._get_any_address()
        context = Context([], tx, unauthorized_address, timestamp=self.get_current_timestamp())
        with self.assertRaises(NotAuthorized):
            runner.call_public_method(self.nc_id, 'change_fee', context, 300)

        # Test dev address change
        new_dev_address, _ = self._get_any_address()
        context = Context([], tx, self.dev_address, timestamp=self.get_current_timestamp())
        runner.call_public_method(self.nc_id, 'change_dev_address', context, new_dev_address)
        self.assertEqual(self.nc_storage.get('dev_address'), new_dev_address)

    def test_nft_operations_edge_cases(self):
        """Test edge cases for NFT deposit and withdrawal operations."""
        self.initialize_contract()
        runner = self.runner
        
        # Register a name and get its owner
        name = "nft-test"
        owner_address = self._register_name(name, self.registration_fee)
        tx = self._get_any_tx()
        
        # Get the NFT token UID
        name_data = runner.call_view_method(self.nc_id, 'get_name_data', name)
        token_uid = bytes.fromhex(name_data['token_uid'])
        
        # Test NFT deposit
        context = Context(
            [NCAction(NCActionType.DEPOSIT, token_uid, 1)],
            tx, owner_address,
            timestamp=self.get_current_timestamp()
        )
        runner.call_public_method(self.nc_id, 'deposit_nft', context, name)
        
        # Test wrong amount deposit
        context = Context(
            [NCAction(NCActionType.DEPOSIT, token_uid, 2)],
            tx, owner_address,
            timestamp=self.get_current_timestamp()
        )
        with self.assertRaises(InvalidAmount):
            runner.call_public_method(self.nc_id, 'deposit_nft', context, name)
            
        # Test unauthorized deposit
        unauthorized_address, _ = self._get_any_address()
        context = Context(
            [NCAction(NCActionType.DEPOSIT, token_uid, 1)],
            tx, unauthorized_address,
            timestamp=self.get_current_timestamp()
        )
        with self.assertRaises(NotAuthorized):
            runner.call_public_method(self.nc_id, 'deposit_nft', context, name)
            
        # Test NFT withdrawal
        context = Context(
            [NCAction(NCActionType.WITHDRAWAL, token_uid, 1)],
            tx, owner_address,
            timestamp=self.get_current_timestamp()
        )
        runner.call_public_method(self.nc_id, 'withdraw_nft', context, name)
        
        # Test unauthorized withdrawal
        context = Context(
            [NCAction(NCActionType.WITHDRAWAL, token_uid, 1)],
            tx, unauthorized_address,
            timestamp=self.get_current_timestamp()
        )
        with self.assertRaises(NotAuthorized):
            runner.call_public_method(self.nc_id, 'withdraw_nft', context, name)

    def test_expiration_edge_cases(self):
        """Test edge cases for name expiration and renewal."""
        self.initialize_contract()
        runner = self.runner
        
        # Register a name
        name = "expiration-test"
        owner_address = self._register_name(name, self.registration_fee)
        tx = self._get_any_tx()
        
        # Get initial expiration info
        expiration_info = runner.call_view_method(self.nc_id, 'get_name_expiration_info', name)
        self.assertEqual(expiration_info['status'], 'active')
        
        # Simulate time passing to expiration
        self.clock.advance(365 * 24 * 60 * 60)  # 1 year
        expiration_info = runner.call_view_method(self.nc_id, 'get_name_expiration_info', name)
        self.assertEqual(expiration_info['status'], 'grace_period')
        
        # Test renewal during grace period
        context = Context(
            [NCAction(NCActionType.DEPOSIT, self.token_uid, self.registration_fee)],
            tx, owner_address,
            timestamp=self.get_current_timestamp()
        )
        runner.call_public_method(self.nc_id, 'renew_name', context, name)
        
        # Verify renewed status
        expiration_info = runner.call_view_method(self.nc_id, 'get_name_expiration_info', name)
        self.assertEqual(expiration_info['status'], 'active')
        
        # Simulate time passing beyond grace period
        self.clock.advance(45 * 24 * 60 * 60)  # 45 days (past 30-day grace period)
        expiration_info = runner.call_view_method(self.nc_id, 'get_name_expiration_info', name)
        self.assertEqual(expiration_info['status'], 'available')
        
        # Try to renew after grace period
        context = Context(
            [NCAction(NCActionType.DEPOSIT, self.token_uid, self.registration_fee)],
            tx, owner_address,
            timestamp=self.get_current_timestamp()
        )
        with self.assertRaises(NameExpired):
            runner.call_public_method(self.nc_id, 'renew_name', context, name)

    def test_token_validation(self):
        self.initialize_contract()

        # Try to register with wrong token
        address_bytes, _ = self._get_any_address()
        wrong_token = b'wrong_token'
        tx = self._get_any_tx()
        action = NCAction(NCActionType.DEPOSIT, wrong_token, self.registration_fee)
        context = Context([action], tx, address_bytes, timestamp=self.get_current_timestamp())
        
        with self.assertRaises(InvalidToken):
            self.runner.call_public_method(self.nc_id, 'create_name', context, "testname")
    
    def _get_any_tx(self):
        genesis = self.manager.tx_storage.get_all_genesis()
        tx = list(genesis)[0]
        return tx
    
    def _get_any_address(self):
        password = os.urandom(12)
        key = KeyPair.create(password)
        address_b58 = key.address
        address_bytes = decode_address(address_b58)
        return address_bytes, key
    
    def _register_name(self, name: str, amount: int, address: Optional[Address] = None) -> Address:
        if address is None:
            address_bytes, _ = self._get_any_address()
        else:
            address_bytes = address
            
        tx = self._get_any_tx()
        action = NCAction(NCActionType.DEPOSIT, self.token_uid, amount)
        context = Context([action], tx, address_bytes, timestamp=self.get_current_timestamp())
        self.runner.call_public_method(self.nc_id, 'create_name', context, name)
        return address_bytes