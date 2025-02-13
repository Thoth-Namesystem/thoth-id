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
    InvalidToken
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

    def test_invalid_name_registration(self):
        self.initialize_contract()

        # Test invalid name format
        with self.assertRaises(InvalidNameFormat):
            self._register_name("a", self.registration_fee)  # Too short
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("UPPERCASE", self.registration_fee)
            
        with self.assertRaises(InvalidNameFormat):
            self._register_name("-start-with-hyphen", self.registration_fee)

        # Test insufficient fee
        with self.assertRaises(InsufficientBalance):
            self._register_name("validname", self.registration_fee - 1)

        # Test duplicate registration
        name = "validname"
        self._register_name(name, self.registration_fee)
        with self.assertRaises(NameAlreadyExists):
            self._register_name(name, self.registration_fee)

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