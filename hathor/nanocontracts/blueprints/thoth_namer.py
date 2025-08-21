from typing import NamedTuple, Optional
from datetime import datetime, timedelta
from hathor.crypto.util import get_address_b58_from_bytes
from hathor.nanocontracts.blueprint import Blueprint
from hathor.nanocontracts.context import Context
from hathor.nanocontracts.exception import NCFail
from hathor.nanocontracts.types import (
    Address,
    Amount,
    NCAction,
    NCActionType,
    TokenUid,
    public,
    view
)
from hathor.crypto.util import get_address_from_public_key

HTR_UID = b'\x00'


class NameRecord(NamedTuple):
    """Record for storing name data and NFT information"""
    token_uid: TokenUid
    owner_address: Optional[Address]  # None means NFT is not deposited
    resolving_address: Address
    expiration_date: str  # Stored as ISO format string

    def update_owner_address(self, new_owner_address: Optional[Address]) -> 'NameRecord':
        """Create a new NameRecord with updated owner_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=new_owner_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date
        )

    def update_resolving_address(self, new_resolving_address: Address) -> 'NameRecord':
        """Create a new NameRecord with updated resolving_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            resolving_address=new_resolving_address,
            expiration_date=self.expiration_date
        )

    def update_expiration_date(self, new_expiration_date: str) -> 'NameRecord':
        """Create a new NameRecord with updated expiration_date."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            resolving_address=self.resolving_address,
            expiration_date=new_expiration_date
        )


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
        self.dev_address = ctx.caller_id

    @public(allow_deposit=True)
    def create_name(self, ctx: Context, name: str, token_symbol: str) -> None:
        """Register a new name under the domain by minting an NFT."""
        if not self.validate_name(name):
            raise InvalidNameFormat
        if name in self.registered_names:
            raise NameAlreadyExists
        if not 6 > len(token_symbol) > 0:
            raise InvalidTokenSymbol

        # Verify fee payment
        years_of_access = self._get_years_of_access(ctx)

        # Calculate expiration date
        expiration_date = datetime.today() + timedelta(days=years_of_access * 365)

        # Mint new NFT and create name record
        token_uid = self._mint_name_nft(name, token_symbol)
        self.registered_names[name] = NameRecord(
            token_uid=token_uid,
            owner_address=ctx.caller_id,  # NFT starts in user's wallet
            resolving_address=ctx.caller_id,
            expiration_date=self._datetime_to_string(expiration_date)
        )
        self.total_fee += self.fee * years_of_access

    @public(allow_actions=False)
    def change_resolving_address(self,
                                 ctx: Context,
                                 name: str,
                                 new_resolving_address: Address) -> None:
        """Change the resolving address of a name when authorized."""
        record = self.registered_names[name]
        if not self._verify_nft_ownership(record.token_uid, ctx.caller_id):
            raise NotAuthorized('You are not the owner of the token.')

        self.registered_names[name] = record.update_resolving_address(new_resolving_address)

    @public(allow_deposit=True)
    def deposit_nft(self, ctx: Context, name: str) -> None:
        """Deposit NFT to enable name management."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        self._check_action_record_token(ctx, record.token_uid, NCActionType.DEPOSIT)
        self.registered_names[name] = record.update_owner_address(new_owner_address=ctx.caller_id)

    @public(allow_withdrawal=True)
    def withdraw_nft(self, ctx: Context, name: str) -> None:
        """Withdraw NFT to enable transfer."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]

        # Verify deposit ownership
        if record.owner_address is None:
            raise OwnershipNotReliable('The token is not deposited \
                on the contract, we can\'t say for sure who is \
                the owner at this moment.')
        if record.owner_address != ctx.caller_id:
            raise NotAuthorized('You are not the owner of the token.')
        self._check_action_record_token(ctx, record.token_uid, NCActionType.WITHDRAWAL)

        # Return NFT and revoke authorization
        self.registered_names[name] = record.update_owner_address(new_owner_address=None)

    @public
    def renew_name(self, ctx: Context, name: str) -> None:
        """Renew a name registration for another period."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        # Verify NFT ownership. This is for the scenario where only the owner can renew its name registration.
        if not self._verify_nft_ownership(record.token_uid, ctx.caller_id):
            raise NotAuthorized

        # Verify fee payment
        years_of_access = self._get_years_of_access(ctx)

        # Calculate new expiration date
        current_expiration = self._string_to_datetime(record.expiration_date)
        new_expiration_date = max(current_expiration, datetime.today()) + timedelta(days=years_of_access * 365)

        # Update expiration in record
        self.registered_names[name] = record.update_expiration_date(new_expiration_date)

        self.total_fee += self.fee * years_of_access

    @view
    def resolve_name(self, name: str) -> str:
        """Get the resolving address associated with a name."""
        self._check_name_expired(name)
        resolving_address = self.registered_names[name].resolving_address
        return get_address_b58_from_bytes(resolving_address)

    @view
    def get_name_data(self, name: str) -> dict[str, str]:
        """Get all data associated with a name in a JSON-serializable format."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        return self._serialize_name_record(record)

    @view
    def get_name_owner(self, name: str) -> Address:
        """Get the name owner's address."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        if record.owner_address:
            raise OwnershipNotReliable('The token is not deposited \
                on the contract, we can\'t say for sure who is \
                the owner at this moment.')

        return get_address_b58_from_bytes(record.owner_address)

    @view
    def get_name_expiration_date(self, name: str) -> datetime:
        """Get the expiration date of a name registration."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        return self._string_to_datetime(record.expiration_date)

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

    def _mint_name_nft(self, name: str, token_symbol: str) -> TokenUid:
        """Mint a new NFT for the name and return its UID."""
        # Create NFT metadata
        nft_name = f'{name[:26]}.{self.domain}'
        
        token_uid = self.syscall.create_token(nft_name, token_symbol, True, True)
        
        # Return the token UID
        return token_uid

    def _verify_nft_ownership(self, token_uid: TokenUid, claimed_owner: Address) -> bool:
        """Verify that the address owns the NFT."""
        # Get the current NFT owner
        current_owner = self._get_nft_owner(token_uid)
        if current_owner is None:
            raise OwnershipNotReliable('The token is not deposited \
                on the contract, we can\'t say for sure who is \
                the owner at this moment.')
        return current_owner == claimed_owner

    def _get_nft_owner(self, name: str) -> Address:
        """Get the current owner of an NFT by looking up to what is on the owner_address at the name record."""
        if name not in self.registered_names:
            raise NameNotFound

        return self.registered_names[name].owner_address

    # No idea if the usage of this function and the "get_public_key" are valid.
    def _get_contract_address(self) -> Address:
        """Get the contract's own address."""
        # Get the contract's public key
        contract_pubkey = self._get_public_key()

        # Convert to address
        return get_address_from_public_key(contract_pubkey)

    def _get_public_key(self) -> bytes:
        """Get the contract's public key."""
        # This should be implemented by the contract runtime
        raise NotImplementedError('Contract public key access not implemented')

    def _get_action(self, ctx: Context) -> NCAction:
        """Return the only action available; fails otherwise."""
        if len(ctx.actions) != 1:
            raise TooManyActions('Only one action supported.')
        action = next(iter(ctx.actions.values()))[0]
        if ctx.caller_id != self.dev_address and action.type == NCActionType.WITHDRAWAL:
            raise WithdrawalNotAllowed('Only dev can withdraw.')
        if action.token_uid != HTR_UID:
            raise InvalidToken('Token different from HTR.')
        return action
    
    def _check_action_record_token(self, ctx: Context,
                                   token_uid: TokenUid,
                                   action_type: NCActionType) -> None:
        """Check if the action record token is HTR."""
        if len(ctx.actions) != 1:
            raise TooManyActions('Only one action supported.')
        action = next(iter(ctx.actions.values()))[0]
        if action.type != action_type:
            raise InvalidActionType(f'Action type different from {action_type.name}.')
        if action.token_uid != token_uid:
            raise InvalidToken(f'Token different from {token_uid.hex()}.')
        if action.amount != 1:
            raise InvalidAmount('Amount must be 1.')
        print(action.token_uid, token_uid)

    def _get_years_of_access(self, ctx: Context):
        """Return the number of years that have been bought."""
        action = self._get_action(ctx)
        if action.amount < self.fee:
            raise InsufficientBalance('Deposit amount is less than fee.')
        if action.amount % self.fee != 0:
            raise InvalidAmount('Deposit amount must be a multiple of the fee.')

        return action.amount // self.fee

    def _check_name_expired(self, name: str) -> bool:
        """Check if a name registration has expired."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        expiration_date = self._string_to_datetime(record.expiration_date)
        if expiration_date < datetime.today():
            raise NameExpired('Name registration has expired')

    def _datetime_to_string(self, dt: datetime) -> str:
        """Convert datetime to ISO format string for storage."""
        return dt.isoformat()

    def _string_to_datetime(self, dt_str: str) -> datetime:
        """Convert ISO format string back to datetime for calculations."""
        return datetime.fromisoformat(dt_str)
    
    def _serialize_name_record(self, record: NameRecord) -> dict[str, str]:
        return {
            'token_uid': record.token_uid.hex(),
            'owner_address': 'None' if record.owner_address is None else get_address_b58_from_bytes(record.owner_address),
            'resolving_address': get_address_b58_from_bytes(record.resolving_address),
            'expiration_date': record.expiration_date
        }
    

class NameNotFound(NCFail):
    """"""
    pass

class NameAlreadyExists(NCFail):
    """"""
    pass

class NotAuthorized(NCFail):
    """"""
    pass

class InvalidNameFormat(NCFail):
    """"""
    pass

class InvalidTokenSymbol(NCFail):
    """"""
    pass

class WithdrawalNotAllowed(NCFail):
    """"""
    pass

class DepositNotAllowed(NCFail):
    """"""
    pass

class InsufficientBalance(NCFail):
    """"""
    pass

class InvalidFee(NCFail):
    """"""
    pass

class InvalidAmount(NCFail):
    """"""
    pass

class InvalidDomain(NCFail):
    """"""
    pass

class TooManyActions(NCFail):
    """"""
    pass

class InvalidToken(NCFail):
    """"""
    pass

class NameExpired(NCFail):
    """"""
    pass

class InvalidExpiration(NCFail):
    """"""
    pass

class OwnershipNotReliable(NCFail):
    """"""
    pass

class InvalidActionType(NCFail):
    """"""
    pass