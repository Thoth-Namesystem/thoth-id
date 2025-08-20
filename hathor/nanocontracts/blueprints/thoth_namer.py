from typing import NamedTuple
from datetime import datetime, timedelta
from hathor.crypto.util import get_address_b58_from_bytes
from hathor.nanocontracts.blueprint import Blueprint
from hathor.nanocontracts.context import Context
from hathor.nanocontracts.exception import NCFail
from hathor.nanocontracts.types import Address, Amount, NCAction, NCActionType, TokenUid, public, view

class NameRecord(NamedTuple):
    """Record for storing name data and NFT information"""
    nft_uid: TokenUid
    owner_address: Address  # None means NFT is not deposited
    data: dict[str, Address|datetime]

# class NameRegistry:
#     def __init__(self, owner_address: Address, resolving_address: Address):
#         self.owner_address = owner_address
#         self.resolving_address = resolving_address
#         self.metadata = {}  # Dictionary to store personalized information

#     def update_owner_address(self, new_owner_address: Address):
#         """Update the resolving address."""
#         self.owner_address = new_owner_address

#     def update_resolving_address(self, new_resolving_address: Address):
#         """Update the resolving address."""
#         self.resolving_address = new_resolving_address

#     def add_metadata(self, key, value):
#         """Add personalized metadata, such as social media or contact info."""
#         self.metadata[key] = value

#     def get_metadata(self, key):
#         """Retrieve metadata by key."""
#         return self.metadata.get(key, "Not found")

#     def remove_metadata(self, key):
#         """Remove metadata by key."""
#         if key in self.metadata:
#             del self.metadata[key]

#     def __str__(self):
#         return str(dict(self))
    
#     def __dict__(self):
#         return {
#             "owner_address": self.owner_address,
#             "resolving_address": self.resolving_address,
#             "metadata": self.metadata
#         }

class ThothNamer(Blueprint):
    """A name service blueprint for registering and managing domain names using NFTs."""
    
    # State variables
    domain: str  # Base domain (e.g., "htr")
    registered_names: dict[str, NameRecord]  # Mapping of names to NameRecord objects
    dev_address: Address  # Developer address for receiving fees
    fee: Amount  # Fee for registering a name
    total_fee: Amount  # Total fees collected
    
    @public
    def initialize(self, ctx: Context, domain: str, fee: Amount) -> None:
        """Initialize the name service with a base domain and registration fee."""
        if not domain:
            raise InvalidDomain('Domain cannot be empty.')
        if fee <= 0:
            raise InvalidFee('Fee must be a positive value.')
            
        self.domain = domain
        self.fee = fee
        self.total_fee = 0
        self.dev_address = ctx.address
        self.registered_names = {}
    
    @public(allow_deposit=True)
    def create_name(self, ctx: Context, name: str) -> None:
        """Register a new name under the domain by minting an NFT."""
        if not self.validate_name(name):
            raise InvalidNameFormat
        if self.check_name_existence(name):
            raise NameAlreadyExists
            
        # Verify fee payment
        years_of_access = self._get_years_of_access(ctx)

        # Calculate expiration date
        expiration_date = datetime.today() + timedelta(days=years_of_access * 365)
            
        # Mint new NFT and create name record
        nft_uid = self._mint_name_nft(name)
        self.registered_names[name] = NameRecord(
            nft_uid=nft_uid,
            owner_address=ctx.address,  # NFT starts in user's wallet
            data={
                'resolving_address': ctx.address,
                'expiration_date': expiration_date
            }
        )
        self.total_fee += self.fee * years_of_access

    @public(allow_actions=[])
    def set_data(self, ctx: Context, name: str, key: str, value: str) -> None:
        """Update name data when authorized."""
        # TODO Implement sanitization on key and value strings before adding them to data.
        self._verify_not_expired(name)

        record = self.registered_names[name]
        if not self._verify_nft_ownership(record.nft_uid, ctx.address):
            raise NotAuthorized
        
        record.data[key] = value
        self.registered_names[name] = record

    @public
    def change_resolving_address(self, ctx: Context, name: str, new_resolving_address: Address) -> None:
        """Change the resolving address of a name when authorized."""
        return self.set_data(ctx, name, 'resolving_address', new_resolving_address)
    
    @public
    def deposit_nft(self, ctx: Context, name: str) -> None:
        """Deposit NFT to enable name management."""
        # TODO See how the deposit works on nanocontracts.
        if name not in self.registered_names:
            raise NameNotFound
        
        record = self.registered_names[name]
        record.owner_address = ctx.address

    @public
    def withdraw_nft(self, ctx: Context, name: str) -> None:
        """Withdraw NFT to enable transfer."""
        if name not in self.registered_names:
            raise NameNotFound
            
        record = self.registered_names[name]
        
        # Verify deposit ownership
        if record.owner_address != ctx.address:
            raise NotAuthorized
            
        # Return NFT and revoke authorization
        self._return_nft_to_owner(record.nft_uid, ctx.address)
        record.owner_address = None

    @public
    def renew_name(self, ctx: Context, name: str) -> None:
        """Renew a name registration for another period."""
        if name not in self.registered_names:
            raise NameNotFound
            
        record = self.registered_names[name]
        
        # Verify NFT ownership. This is for the scenario where only the owner can renew its name registration.
        if not self._verify_nft_ownership(record.nft_uid, ctx.address):
            raise NotAuthorized
            
        # Verify fee payment
        years_of_access = self._get_years_of_access(ctx)
            
        # Calculate new expiration date
        current_expiration = record.data['expiration_date']
        new_expiration = max(current_expiration, datetime.today()) + timedelta(days=years_of_access * 365)
        
        # Update expiration in record
        record.data['expiration_date'] = new_expiration
        
        self.total_fee += self.fee * years_of_access
    
    @view
    def resolve_name(self, name: str) -> str:
        """Get the resolving address associated with a name."""
        self._verify_not_expired(name)
        return self.registered_names[name].data['resolving_address']
    
    @view
    def get_name_data(self, name: str) -> dict[str, any]:
        """Get all data associated with a name."""
        if name not in self.registered_names:
            raise NameNotFound
            
        return self.registered_names[name].data
    
    @view
    def get_name_owner(self, name: str) -> Address:
        """Get the name owner's address."""
        if name not in self.registered_names:
            raise NameNotFound
        
        record = self.registered_names[name]
        if record.owner_address:
            raise InfoNotReliable("The token is not deposited on the contract, we can\'t say for sure who is the owner at this moment.")

        return get_address_b58_from_bytes(record.owner_address)

    @view
    def get_name_expiration(self, name: str) -> datetime.date:
        """Get the expiration date of a name registration."""
        if name not in self.registered_names:
            raise NameNotFound
            
        record = self.registered_names[name]
        return record.data['expiration_date']

    @view
    def validate_name(self, name: str) -> bool:
        """Verify if the name exists and is valid."""
        # Check if name is empty
        if not name:
            return False
            
        # Check length (e.g., between 3 and 32 characters)
        if len(name) < 3 or len(name) > 32:
            return False
            
        # Only allow lowercase letters, numbers, and hyphens
        allowed_chars = set('abcdefghijklmnopqrstuvwxyz0123456789-')
        if not all(c in allowed_chars for c in name):
            return False
            
        # Don't allow names starting or ending with hyphen
        if name[0] == '-' or name[-1] == '-':
            return False
            
        return True
    
    @view
    def get_dev_address(self) -> Address:
        """Get the developer's address."""
        return get_address_b58_from_bytes(self.dev_address)
    
    @view
    def get_contract_domain(self) -> str:
        """Get the contract domain."""
        return self.domain

    def _mint_name_nft(self, name: str) -> TokenUid:
        """Mint a new NFT for the name and return its UID."""
        # Create NFT metadata
        nft_name = f'{name}.{self.domain}'
        
        token_uid = self.syscall.create_token(nft_name, nft_name, True, True)
        
        # Return the token UID
        return token_uid

    def _verify_nft_ownership(self, nft_uid: TokenUid, claimed_owner: Address) -> bool:
        """Verify that the address owns the NFT."""
        # Get the current NFT owner
        current_owner = self._get_nft_owner(nft_uid)
        return current_owner == claimed_owner

    def _return_nft_to_owner(self, nft_uid: TokenUid, owner: Address) -> None:
        """Return a deposited NFT to its owner."""
        # TODO See how to create a tx that returns the token to the owner.
        ...

    def _get_nft_owner(self, name: str) -> Address:
        """Get the current owner of an NFT by looking up to what is on the owner_address at the name record."""
        if name not in self.registered_names:
            raise NameNotFound

        return self.registered_names[name].owner_address

    def _create_nft_transfer_tx(self, nft_uid: TokenUid, from_address: Address, to_address: Address, amount: int):
        """Create a transaction to transfer an NFT."""
        from hathor.transaction import Transaction
        from hathor.transaction.scripts import P2PKH_SCRIPT_HASH
        
        # Create inputs from the current owner's NFT
        inputs = [{
            'tx_id': nft_uid,
            'index': 0,
            'data': b'',  # No specific data needed for NFT transfer
            'script': P2PKH_SCRIPT_HASH  # Using standard P2PKH for simplicity
        }]
        
        # Create outputs to the new owner
        outputs = [{
            'address': to_address,
            'value': amount,
            'token_data': 0,  # NFT transfer
            'script': P2PKH_SCRIPT_HASH
        }]
        
        # Create and return the transaction
        return Transaction(
            version=1,
            inputs=inputs,
            outputs=outputs,
            tokens=[nft_uid]
        )

    # No idea if the usage of this function and the "get_public_key" are valid.
    def get_contract_address(self) -> Address:
        """Get the contract's own address."""
        from hathor.crypto.util import get_address_from_public_key
        
        # Get the contract's public key
        contract_pubkey = self.get_public_key()
        
        # Convert to address
        return get_address_from_public_key(contract_pubkey)

    def get_public_key(self) -> bytes:
        """Get the contract's public key."""
        # This should be implemented by the contract runtime
        raise NotImplementedError('Contract public key access not implemented')

    def _get_action(self, ctx: Context) -> NCAction:
        """Return the only action available; fails otherwise."""
        if len(ctx.actions) != 1:
            raise TooManyActions('Only one action supported.')
        action = next(iter(ctx.actions.values()))
        if ctx.address != self.dev_address and action.type == NCActionType.WITHDRAWAL:
            raise WithdrawalNotAllowed('Only dev can withdraw.')
        if action.token_uid == b'00':
            raise InvalidToken('Token different from HTR.')
        return action
    
    def _get_years_of_access(self, ctx: Context):
        """Return the number of years that have been bought."""
        action = self._get_action(ctx)
        if action.amount < self.fee:
            raise InsufficientBalance('Deposit amount is less than fee.')
        if action.amount % self.fee != 0:
            raise InvalidAmount('Deposit amount must be a multiple of the fee.')

        return action.amount // self.fee

    def _verify_not_expired(self, name: str) -> None:
        """Verify that a name hasn't expired, raise exception if it has."""
        if self._check_name_expired(name):
            raise NameExpired('Name registration has expired')

    def _check_name_expired(self, name: str) -> bool:
        """Check if a name registration has expired."""
        if name not in self.registered_names:
            raise NameNotFound
            
        record = self.registered_names[name]
        expiration_date = record.data['expiration_date']
        return expiration_date < datetime.today()

    def _create_nft_metadata_update_tx(self, nft_uid: TokenUid, metadata: dict):
        """Create a transaction to update NFT metadata."""
        from hathor.transaction import Transaction
        from hathor.transaction.scripts import P2PKH_SCRIPT_HASH
        
        # Create inputs from the current NFT state
        inputs = [{
            'tx_id': nft_uid,
            'index': 0,
            'data': b'',
            'script': P2PKH_SCRIPT_HASH
        }]
        
        # Create outputs with updated metadata
        outputs = [{
            'address': self.get_contract_address(),
            'value': 1,  # NFTs have amount 1
            'token_data': 0,
            'script': P2PKH_SCRIPT_HASH,
            'metadata': metadata
        }]
        
        # Create and return the transaction
        return Transaction(
            version=1,
            inputs=inputs,
            outputs=outputs,
            tokens=[nft_uid]
        )
    

class NameNotFound(NCFail):
    pass

class NameAlreadyExists(NCFail):
    pass

class NotAuthorized(NCFail):
    pass

class InvalidNameFormat(NCFail):
    pass

class WithdrawalNotAllowed(NCFail):
    pass

class DepositNotAllowed(NCFail):
    pass

class InsufficientBalance(NCFail):
    pass

class InvalidFee(NCFail):
    pass

class InvalidAmount(NCFail):
    pass

class InvalidDomain(NCFail):
    pass

class TooManyActions(NCFail):
    pass

class InvalidToken(NCFail):
    pass

class NameExpired(NCFail):
    pass

class InvalidExpiration(NCFail):
    pass

class InfoNotReliable(NCFail):
    pass