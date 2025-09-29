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

# Validation constants
MAX_PROFILE_DATA_ENTRIES = 20     # Maximum number of profile data entries
MAX_PROFILE_KEY_LENGTH = 50       # Maximum length for profile data keys
MAX_PROFILE_VALUE_LENGTH = 1000   # Maximum length for profile data values
MAX_TOKEN_SYMBOL_LENGTH = 5       # Maximum length for token symbols
MAX_TOTAL_PROFILE_SIZE = 10000    # Maximum total size of all profile data in bytes

# Time constants (in days)
GRACE_PERIOD_DAYS = 30            # Grace period after expiration before name becomes available


class NameRecord(NamedTuple):
    """Record for storing name data and NFT information"""
    token_uid: TokenUid
    owner_address: Optional[Address]  # None means NFT is not deposited
    manager_address: Address
    resolving_address: Address
    expiration_date: str  # Stored as ISO format string
    data: dict[str, str]  # Additional profile data

    def update_owner_address(self, new_owner_address: Optional[Address]) -> 'NameRecord':
        """Create a new NameRecord with updated owner_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=new_owner_address,
            manager_address=self.manager_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date,
            data=self.data
        )

    def update_resolving_address(self, new_resolving_address: Address) -> 'NameRecord':
        """Create a new NameRecord with updated resolving_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            manager_address=self.manager_address,
            resolving_address=new_resolving_address,
            expiration_date=self.expiration_date,
            data=self.data
        )

    def update_expiration_date(self, new_expiration_date: str) -> 'NameRecord':
        """Create a new NameRecord with updated expiration_date."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            manager_address=self.manager_address,
            resolving_address=self.resolving_address,
            expiration_date=new_expiration_date,
            data=self.data
        )

    def update_manager_address(self, new_manager_address: Address) -> 'NameRecord':
        """Create a new NameRecord with updated manager_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            manager_address=new_manager_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date,
            data=self.data
        )

    def update_data(self, key: str, value: str) -> 'NameRecord':
        """Create a new NameRecord with updated data field."""
        new_data = dict(self.data)  # Create a copy of the current data
        new_data[key] = value
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            manager_address=self.manager_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date,
            data=new_data
        )
        
    def remove_data(self, key: str) -> 'NameRecord':
        """Create a new NameRecord with a data key removed."""
        new_data = dict(self.data)  # Create a copy of the current data
        if key in new_data:
            del new_data[key]
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            manager_address=self.manager_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date,
            data=new_data
        )


class ThothNamer(Blueprint):
    """A name service blueprint for registering and managing domain names using NFTs."""

    # State variables
    domain: str  # Base domain (e.g., "htr")
    registered_names: dict[str, NameRecord]  # Mapping of names to NameRecord objects
    manager_names: dict[Address, list[str]]  # Mapping of manager addresses to their managed names
    dev_address: Address  # Developer address for receiving fees
    base_fee: Amount  # Base fee for registering a name
    total_fee: Amount  # Total fees collected
    fee_multiplier: dict[int, int]

    @public
    def initialize(self, ctx: Context, domain: str, base_fee: Amount) -> None:
        """Initialize the name service with a base domain and registration fee."""
        if not domain:
            raise InvalidDomain('Domain cannot be empty.')
        if base_fee <= 0:
            raise InvalidFee('Fee must be a positive value.')

        self.domain = domain
        self.base_fee = base_fee
        self.total_fee = 0
        self.dev_address = ctx.caller_id
        self.fee_multiplier[3] = 20
        self.fee_multiplier[4] = 10
        self.fee_multiplier[5] = 1

    @public(allow_deposit=True, allow_withdrawal=False)
    def create_name(self, ctx: Context, name: str, token_symbol: str) -> None:
        """Register a new name under the domain by minting an NFT."""
        if not self.validate_name(name):
            raise InvalidNameFormat
        if not self.is_name_available(name):
            if name in self.registered_names:
                record = self.registered_names[name]
                expiration_date = self._string_to_datetime(record.expiration_date)
                if expiration_date > datetime.today():
                    raise NameAlreadyExists('Name is already registered')
                else:
                    grace_period_end = expiration_date + timedelta(days=GRACE_PERIOD_DAYS)
                    raise NameInGracePeriod(f'Name is in grace period until {grace_period_end.isoformat()}')
        if not (0 < len(token_symbol) <= MAX_TOKEN_SYMBOL_LENGTH):
            raise InvalidTokenSymbol(f'Token symbol must be between 1 and {MAX_TOKEN_SYMBOL_LENGTH} characters')

        # Verify fee payment
        fee = self.calculate_fee(name)
        years_of_access = self._get_years_of_access(ctx, fee)

        # Calculate expiration date
        expiration_date = datetime.today() + timedelta(days=years_of_access * 365)

        # Mint new NFT and create name record
        token_uid = self._mint_name_nft(name, token_symbol)
        self.registered_names[name] = NameRecord(
            token_uid=token_uid,
            owner_address=ctx.caller_id,  # NFT starts in user's wallet
            manager_address=ctx.caller_id,
            resolving_address=ctx.caller_id,
            expiration_date=self._datetime_to_string(expiration_date),
            data={}  # Initialize with empty data dictionary
        )
        
        # Add to manager's list of names
        self._add_name_to_manager(ctx.caller_id, name)
        
        self.total_fee += fee * years_of_access

    @public(allow_actions=False)
    def delete_profile_data(self, ctx: Context, name: str, key: str) -> None:
        """Delete a field from the profile data.
        
        Args:
            ctx: The context object
            name: The name to update
            key: The profile data key to delete
            
        Only the manager can delete profile data.
        """
        if not self.validate_name(name):
            raise InvalidNameFormat
        if name not in self.registered_names:
            raise NameNotFound
            
        record = self.registered_names[name]
        
        # Check if key exists
        if key not in record.data:
            raise InvalidDataKey('Key does not exist in profile data')
            
        # Authorization check
        if record.manager_address != ctx.caller_id:
            raise NotAuthorized('Only the manager can delete profile data')
            
        self.registered_names[name] = record.remove_data(key)
    
    @public(allow_actions=False)
    def update_profile_data(self, ctx: Context, name: str, key: str, value: str) -> None:
        """Update a specific field in the profile data.
        
        Args:
            ctx: The context object
            name: The name to update
            key: The profile data key (must be 3-50 chars, alphanumeric and underscores)
            value: The profile data value (must be 1-1000 chars)
            
        Only the manager can update profile data.
        """
        if not self.validate_name(name):
            raise InvalidNameFormat
        if name not in self.registered_names:
            raise NameNotFound
        
        record = self.registered_names[name]
        # Validate total number of keys
        if len(record.data) >= MAX_PROFILE_DATA_ENTRIES and key not in record.data:
            raise TooManyDataKeys(f'Maximum of {MAX_PROFILE_DATA_ENTRIES} profile data keys allowed')
            
        # Validate key format and total size
        self.validate_key_format(key, value, record.data)
        
        # Authorization check
        if record.manager_address != ctx.caller_id:
            raise NotAuthorized('Only the manager can update profile data')

        self.registered_names[name] = record.update_data(key, value)

    @public(allow_actions=False)
    def change_manager_address(self,
                               ctx: Context,
                               name: str,
                               new_manager_address: Address) -> None:
        """Change the manager address of a name when authorized.
        
        The manager can be changed by:
        1. The NFT owner (when NFT is deposited)
        2. The current manager (no deposit needed)
        """
        record = self.registered_names[name]
        
        # Check authorization
        is_owner = record.owner_address == ctx.caller_id
        is_manager = record.manager_address == ctx.caller_id
        
        if not (is_owner or is_manager):
            raise NotAuthorized('Only the owner or current manager can change the manager address')
            
        # If caller is owner, verify NFT is deposited
        if is_owner and record.owner_address is None:
            raise OwnershipNotReliable('The token must be deposited to change manager as owner')
            
        # Update manager mappings
        self._update_name_manager(name, record.manager_address, new_manager_address)
            
        self.registered_names[name] = record.update_manager_address(new_manager_address)

    @public(allow_actions=False)
    def change_resolving_address(self,
                                 ctx: Context,
                                 name: str,
                                 new_resolving_address: Address) -> None:
        """Change the resolving address of a name when authorized.
        
        Only the manager can change the resolving address.
        """
        record = self.registered_names[name]
        if record.manager_address != ctx.caller_id:
            raise NotAuthorized('Only the manager can change the resolving address')

        self.registered_names[name] = record.update_resolving_address(new_resolving_address)

    @public(allow_deposit=True, allow_withdrawal=False)
    def deposit_nft(self, ctx: Context, name: str) -> None:
        """Deposit NFT to enable name management."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        self._check_action_record_token(ctx, record.token_uid, NCActionType.DEPOSIT)
        self.registered_names[name] = record.update_owner_address(new_owner_address=ctx.caller_id)

    @public(allow_deposit=False, allow_withdrawal=True)
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

    @public(allow_deposit=True, allow_withdrawal=False)
    def renew_name(self, ctx: Context, name: str) -> None:
        """Renew a name registration for another period."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]

        # Verify fee payment
        fee = self.calculate_fee(name)
        years_of_access = self._get_years_of_access(ctx, fee)

        # Calculate new expiration date
        current_expiration = self._string_to_datetime(record.expiration_date)
        new_expiration_date = max(current_expiration, datetime.today()) + timedelta(days=years_of_access * 365)

        # Update expiration in record
        self.registered_names[name] = record.update_expiration_date(new_expiration_date)

        self.total_fee += fee * years_of_access

    @public(allow_actions=False)
    def change_fee(self, ctx: Context, new_fee: Amount) -> None:
        """Change the fee."""
        self._only_dev(ctx)
        if new_fee <= 0:
            raise InvalidFee('Fee must be a positive value.')
        self.base_fee = new_fee

    @public(allow_actions=False)
    def change_fee_multiplier(self, ctx: Context, length: int, new_multiplier: int) -> None:
        """
            Change the fee multiplier.

            The possible lengths are: 3, 4, 5. 
            The multiplier of length 5 will be used for all other lengths.
        """
        self._only_dev(ctx)
        if length not in self.fee_multiplier:
            raise InvalidLength('Length not found in fee multiplier. Must be 3, 4 or 5. \
                                Length 5 will be used for all other lengths.')
        if new_multiplier <= 0:
            raise InvalidMultiplier('Multiplier must be a positive value.')
        self.fee_multiplier[length] = new_multiplier

    @view
    def is_name_available(self, name: str) -> bool:
        """Check if a name is available for registration.
        
        A name is available if:
        1. It doesn't exist in the registry, or
        2. It's expired AND past the grace period
        """
        if name not in self.registered_names:
            return True
            
        record = self.registered_names[name]
        expiration_date = self._string_to_datetime(record.expiration_date)
        grace_period_end = expiration_date + timedelta(days=GRACE_PERIOD_DAYS)
        
        return datetime.today() > grace_period_end

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
    def get_name_expiration_info(self, name: str) -> dict[str, str]:
        """Get detailed expiration information for a name.
        
        Returns a dictionary containing:
        - expiration_date: The expiration date in ISO format
        - grace_period_end: The grace period end date in ISO format
        - status: Current status (active, grace_period, or available)
        - days_remaining: Days until expiration (or until grace period ends if expired)
        """
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        expiration_date = self._string_to_datetime(record.expiration_date)
        grace_period_end = expiration_date + timedelta(days=GRACE_PERIOD_DAYS)
        today = datetime.today()
        
        if today < expiration_date:
            status = 'active'
        elif today < grace_period_end:
            status = 'grace_period'
        else:
            status = 'available'
            
        return {
            'expiration_date': expiration_date.isoformat(),
            'grace_period_end': grace_period_end.isoformat(),
            'status': status,
        }
        
    @view
    def get_name_expiration_date(self, name: str) -> datetime:
        """Get the expiration date of a name registration."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        return self._string_to_datetime(record.expiration_date)

    @view
    def validate_name(self, name: str) -> bool:
        """Verify if the name exists and is valid.
        
        Rules:
        - 3-80 characters long
        - Only ASCII lowercase letters, numbers, and single hyphens
        - No consecutive hyphens
        - No hyphen at start or end
        - No unicode homoglyphs or control characters
        """
        # Check if name is empty or not a string
        if not isinstance(name, str) or not name:
            return False
        
        # Check if name contains any non-ASCII characters
        if not name.isascii():
            return False
        
        # Check length (between 3 and 80 characters)
        if len(name) < 3 or len(name) > 80:
            return False
        
        # Don't allow names starting or ending with hyphen
        if name[0] == '-' or name[-1] == '-':
            return False
        
        # Don't allow consecutive hyphens
        if '--' in name:
            return False
            
        # Only allow lowercase letters, numbers, and hyphens
        name_without_hyphens = name.replace('-', '')
        if not name_without_hyphens.islower() or not name_without_hyphens.isalnum():
            return False
        
        return True
    
    @view
    def validate_key_format(self, key: str, value: str) -> bool:
        """Validate key format and value.
        
        Rules:
        - Key must be 1-50 characters
        - Key must be alphanumeric with underscores
        - Value must be 1-1000 characters
        - Value must be valid UTF-8
        - No control characters allowed (except newline, tab)
        """
        # Validate key
        if not isinstance(key, str) or not key or len(key) > MAX_PROFILE_KEY_LENGTH:
            raise InvalidDataKey(f'Key must be between 1 and {MAX_PROFILE_KEY_LENGTH} characters')
        
        # Only allow alphanumeric and underscores in keys
        if not key.replace('_', '').isalnum():
            raise InvalidDataKey('Key must contain only letters, numbers, and underscores')
        
        # Validate value
        if not isinstance(value, str) or not value or len(value) > MAX_PROFILE_VALUE_LENGTH:
            raise InvalidDataValue(f'Value must be between 1 and {MAX_PROFILE_VALUE_LENGTH} characters')
            
        # Check for control characters in value (allow newline, tab, carriage return)
        if value.find('\x00') >= 0:  # Null byte
            raise InvalidDataValue('Value contains invalid control characters')
            
        return True

    @view
    def get_dev_address(self) -> Address:
        """Get the developer's address."""
        return get_address_b58_from_bytes(self.dev_address)

    @view
    def get_contract_domain(self) -> str:
        """Get the contract domain."""
        return self.domain
        
    @view
    def check_name_ownership(self, name: str, address: Address) -> bool:
        """Check if a specific name is owned by an address.
        
        Args:
            name: The name to check
            address: The address to verify ownership for
            
        Returns:
            bool: True if the address owns the name, False otherwise
        """
        if name not in self.registered_names:
            return False
            
        record = self.registered_names[name]
        if record.owner_address != address:
            return False
            
        # Check if expired
        expiration_date = self._string_to_datetime(record.expiration_date)
        if expiration_date < datetime.today():
            return False
            
        return True
        
    @view
    def check_name_status(self, name: str) -> str:
        """Check the status of a specific name.
        
        Args:
            name: The name to check
            
        Returns:
            str: 'active', 'expired', or 'available'
        """
        if name not in self.registered_names:
            return 'available'
            
        record = self.registered_names[name]
        expiration_date = self._string_to_datetime(record.expiration_date)
        
        if expiration_date < datetime.today():
            grace_period_end = expiration_date + timedelta(days=GRACE_PERIOD_DAYS)
            if datetime.today() > grace_period_end:
                return 'available'
            return 'grace_period'
            
        return 'active'
    
    @view
    def get_fee_info(self, name: str) -> dict[str, int]:
        """Get detailed fee information for a name.
        
        Returns a dictionary containing:
        - base_fee: The base registration fee
        - multiplier: The fee multiplier for this name length
        - total_fee: The total fee required (base_fee * multiplier)
        """
        if not self.validate_name(name):
            raise InvalidNameFormat
            
        length = len(name)
        multiplier = self.fee_multiplier[5]  # Default multiplier
        if length in self.fee_multiplier:
            multiplier = self.fee_multiplier[length]
            
        return {
            'base_fee': self.base_fee,
            'multiplier': multiplier,
            'total_fee': self.base_fee * multiplier
        }
        
    @view
    def calculate_fee(self, name: str) -> Amount:
        """Calculate the fee for a name based on its length."""
        return self.get_fee_info(name)['total_fee']
    
    @view
    def get_fee_multiplier(self, length: int) -> int:
        """Get the fee multiplier for a given length."""
        if length not in self.fee_multiplier:
            raise InvalidLength('Length not found in fee multiplier. Must be 3, 4 or 5. \
                                Length 5 will be used for all other lengths.')
        return self.fee_multiplier[length]
        
    @view
    def get_manager_names(self, manager_address: Address) -> list[str]:
        """Get all names managed by a specific address.
        
        Args:
            manager_address: The address to check
            
        Returns:
            list[str]: List of names managed by this address (empty if none)
        """
        return self.manager_names.get(manager_address, [])
        
    @view
    def get_fee_structure(self) -> dict[str, dict[str, int]]:
        """Get the complete fee structure information.
        
        Returns a dictionary containing:
        - base_fee: The base registration fee
        - multipliers: Dictionary of length-to-multiplier mappings
        - default_multiplier: The multiplier used for lengths > 5
        """
        return {
            'base_fee': self.base_fee,
            'multipliers': self.fee_multiplier,
            'default_multiplier': self.fee_multiplier[5]
        }

    def _only_dev(self, ctx: Context) -> None:
        """Check if the caller is the developer."""
        if ctx.caller_id != self.dev_address:
            raise NotAuthorized

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

    def _get_years_of_access(self, ctx: Context, fee: Amount):
        """Return the number of years that have been bought."""
        action = self._get_action(ctx)
        if action.amount < fee:
            raise InsufficientBalance(f'Deposit amount is less than fee ({fee}).')
        if action.amount % fee != 0:
            raise InvalidAmount(f'Deposit amount must be a multiple of the fee ({fee}).')

        return action.amount // fee

    def _check_name_expired(self, name: str) -> bool:
        """Check if a name registration has expired."""
        if name not in self.registered_names:
            raise NameNotFound

        record = self.registered_names[name]
        expiration_date = self._string_to_datetime(record.expiration_date)
        if expiration_date < datetime.today():
            raise NameExpired('Name registration has expired')

    def _datetime_to_string(self, dt: datetime) -> str:
        """Convert datetime to ISO format string for storage.
        
        Args:
            dt: The datetime object to convert (must be timezone-naive)
            
        Returns:
            str: The datetime in ISO format
        """
        if dt.tzinfo is not None:
            raise InvalidExpiration('Datetime must be timezone-naive')
            
        return dt.isoformat()

    def _string_to_datetime(self, dt_str: str) -> datetime:
        """Convert ISO format string back to datetime for calculations.
        
        Args:
            dt_str: The ISO format datetime string
            
        Returns:
            datetime: The parsed datetime object
        """
        return datetime.fromisoformat(dt_str)
    
    def _add_name_to_manager(self, manager_address: Address, name: str) -> None:
        """Add a name to a manager's list of managed names."""
        if manager_address not in self.manager_names:
            self.manager_names[manager_address] = []
        if name not in self.manager_names[manager_address]:
            self.manager_names[manager_address].append(name)
            
    def _remove_name_from_manager(self, manager_address: Address, name: str) -> None:
        """Remove a name from a manager's list of managed names."""
        if manager_address in self.manager_names:
            if name in self.manager_names[manager_address]:
                names_tuple = self.manager_names[manager_address]
                names_list = list(names_tuple)
                names_list.remove(name)
                self.manager_names[manager_address] = tuple(names_list)
            # Clean up empty lists
            if not self.manager_names[manager_address]:
                del self.manager_names[manager_address]
                
    def _update_name_manager(self, name: str, old_manager: Address, new_manager: Address) -> None:
        """Update manager mappings when a name's manager changes."""
        self._remove_name_from_manager(old_manager, name)
        self._add_name_to_manager(new_manager, name)
    
    def _serialize_name_record(self, record: NameRecord) -> dict[str, str]:
        base_data = {
            'token_uid': record.token_uid.hex(),
            'owner_address': 'None' if record.owner_address is None else get_address_b58_from_bytes(record.owner_address),
            'manager_address': get_address_b58_from_bytes(record.manager_address),
            'resolving_address': get_address_b58_from_bytes(record.resolving_address),
            'expiration_date': record.expiration_date
        }
        # Add profile data
        base_data.update(record.data)
        return base_data
    

class NameNotFound(NCFail):
    """Raised when attempting to access a name that is not registered in the system.
    
    This can happen when trying to manage, resolve, or query information about
    a non-existent name.
    """
    pass

class NameAlreadyExists(NCFail):
    """Raised when attempting to register a name that is already taken.
    
    Users should check name availability before attempting registration.
    """
    pass

class NotAuthorized(NCFail):
    """Raised when an address attempts an operation without proper authorization.
    
    This includes:
    - Non-owner trying to manage NFT
    - Non-manager trying to update resolving address
    - Non-dev trying to change contract settings
    """
    pass

class InvalidNameFormat(NCFail):
    """Raised when a name doesn't meet the format requirements.
    
    Names must:
    - Be 3-80 characters long
    - Contain only lowercase letters, numbers, and hyphens
    - Not start or end with a hyphen
    - Not contain consecutive hyphens
    """
    pass

class InvalidTokenSymbol(NCFail):
    """Raised when a token symbol doesn't meet the requirements.
    
    Token symbols must:
    - Be 1-5 characters long
    - Be unique within the system
    """
    pass

class WithdrawalNotAllowed(NCFail):
    """Raised when attempting an unauthorized withdrawal operation.
    
    Only the owner of deposited NFTs can withdraw them.
    """
    pass

class DepositNotAllowed(NCFail):
    """Raised when attempting an unauthorized deposit operation.
    
    Deposits must be of valid NFTs and by their owners.
    """
    pass

class InsufficientBalance(NCFail):
    """Raised when attempting an operation with insufficient HTR balance.
    
    The deposit amount must cover the required fee for the operation.
    """
    pass

class InvalidFee(NCFail):
    """Raised when an invalid fee value is provided.
    
    Fees must be positive values and appropriate for the operation.
    """
    pass

class InvalidAmount(NCFail):
    """Raised when an invalid amount is provided for an operation.
    
    Amounts must be appropriate for the specific operation (e.g., NFT amount must be 1).
    """
    pass

class InvalidDomain(NCFail):
    """Raised when attempting to set an invalid domain for the contract.
    
    The domain must be a non-empty string.
    """
    pass

class TooManyActions(NCFail):
    """Raised when more than one action is provided for an operation.
    
    Most operations support only a single action at a time.
    """
    pass

class InvalidToken(NCFail):
    """Raised when an operation involves an invalid or unexpected token.
    
    This includes using non-HTR tokens for fees or incorrect NFTs.
    """
    pass

class NameExpired(NCFail):
    """Raised when attempting to use an expired name.
    
    Names must be renewed before expiration to maintain functionality.
    """
    pass

class InvalidExpiration(NCFail):
    """Raised when handling invalid expiration dates.
    
    Dates must be:
    - Valid ISO format strings
    - Timezone-naive
    - Between years 2020-2100
    """
    pass

class OwnershipNotReliable(NCFail):
    """Raised when ownership status cannot be reliably determined.
    
    This happens when:
    - NFT is not deposited in the contract
    - Ownership verification fails
    """
    pass

class InvalidActionType(NCFail):
    """Raised when an action's type doesn't match the expected type.
    
    Actions must match the operation being performed (deposit/withdrawal).
    """
    pass

class InvalidLength(NCFail):
    """Raised when an invalid length is provided for fee calculation.
    
    Length must be one of the supported values (3, 4, or 5).
    """
    pass

class InvalidMultiplier(NCFail):
    """Raised when an invalid fee multiplier is provided.
    
    Multipliers must be positive values.
    """
    pass

class InvalidDataKey(NCFail):
    """Raised when trying to update a profile data field with an invalid key format."""
    pass

class InvalidDataValue(NCFail):
    """Raised when trying to update a profile data field with an invalid value format."""
    pass

class TooManyDataKeys(NCFail):
    """Raised when trying to add more profile data keys than the maximum allowed."""
    pass

class NameInGracePeriod(NCFail):
    """Raised when attempting to register a name that is in its grace period.
    
    After expiration, names have a grace period during which the original owner
    can still renew them before they become available to others.
    """
    pass

class InvalidParameter(NCFail):
    """Raised when an invalid parameter value is provided to a method."""
    pass