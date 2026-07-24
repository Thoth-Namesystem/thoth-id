from typing import NamedTuple
from hathor import (
    HATHOR_TOKEN_UID,
    Blueprint,
    BlueprintId,
    Context,
    NCFail,
    Address,
    Amount,
    NCAction,
    NCActionType,
    TokenUid,
    Timestamp,
    public,
    view,
    export
)


SECONDS_PER_YEAR = 365 * 24 * 60 * 60
SECONDS_PER_DAY = 24 * 60 * 60

# Default configuration values
DEFAULT_MAX_MANAGED_NAMES = 100
DEFAULT_MAX_PROFILE_DATA_ENTRIES = 20
DEFAULT_MAX_PROFILE_KEY_LENGTH = 50
DEFAULT_MAX_PROFILE_VALUE_LENGTH = 200
DEFAULT_MAX_TOKEN_SYMBOL_LENGTH = 5
DEFAULT_MAX_TOTAL_PROFILE_SIZE = 10000
DEFAULT_GRACE_PERIOD_DAYS = 30


class NameRecord(NamedTuple):
    """Record for storing name data and NFT information"""
    token_uid: TokenUid
    owner_address: Address
    is_deposited: bool
    manager_address: Address
    resolving_address: Address
    expiration_date: Timestamp  # Stored as timestamp

    def update_owner_address(self, new_owner_address: Address) -> 'NameRecord':
        """Create a new NameRecord with updated owner_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=new_owner_address,
            is_deposited=self.is_deposited,
            manager_address=self.manager_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date
        )

    def update_resolving_address(self, new_resolving_address: Address) -> 'NameRecord':
        """Create a new NameRecord with updated resolving_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            is_deposited=self.is_deposited,
            manager_address=self.manager_address,
            resolving_address=new_resolving_address,
            expiration_date=self.expiration_date
        )

    def update_expiration_date(self, new_expiration_date: Timestamp) -> 'NameRecord':
        """Create a new NameRecord with updated expiration_date."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            is_deposited=self.is_deposited,
            manager_address=self.manager_address,
            resolving_address=self.resolving_address,
            expiration_date=new_expiration_date
        )

    def update_manager_address(self, new_manager_address: Address) -> 'NameRecord':
        """Create a new NameRecord with updated manager_address."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            is_deposited=self.is_deposited,
            manager_address=new_manager_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date
        )

    def toggle_is_deposited(self) -> 'NameRecord':
        """Create a new NameRecord with updated is_deposited."""
        return NameRecord(
            token_uid=self.token_uid,
            owner_address=self.owner_address,
            is_deposited=not self.is_deposited,
            manager_address=self.manager_address,
            resolving_address=self.resolving_address,
            expiration_date=self.expiration_date
        )

@export
class ThothNamer(Blueprint):
    """A name service blueprint for registering and managing domain names using NFTs."""

    # State variables
    domain: str  # Base domain (e.g., "htr")
    registered_names: dict[str, NameRecord]  # Mapping of names to NameRecord objects
    name_profile_data: dict[str, dict[str, str]]  # Mapping of names to their profile data
    name_profile_keys: dict[str, list[str]]  # Mapping of names to list of their profile data keys
    manager_names: dict[Address, list[str]]  # Mapping of manager addresses to their managed names
    manager_primary_name: dict[Address, str]  # Mapping of manager addresses to their primary name
    dev_address: Address  # Developer address for receiving fees
    base_fee: Amount  # Base fee for registering a name
    total_fee: Amount  # Total fees collected
    fee_multiplier: dict[int, int]
    max_profile_data_entries: int # Maximum number of profile data entries
    max_profile_key_length: int # Maximum length for profile data keys
    max_profile_value_length: int # Maximum length for profile data values
    max_token_symbol_length: int # Maximum length for token symbols
    max_total_profile_size: int # Maximum total size of all profile data in bytes
    grace_period_days: int # Grace period after expiration before name becomes available
    max_managed_names: int # Maximum number of names a single address can manage
    contract_version: str # Contract version

    @public
    def initialize(self, 
                   ctx: Context, 
                   domain: str, 
                   base_fee: Amount,
                   max_profile_data_entries: int,
                   max_profile_key_length: int,
                   max_profile_value_length: int,
                   max_token_symbol_length: int,
                   max_total_profile_size: int,
                   grace_period_days: int,
                   max_managed_names: int) -> None:
        """Initialize the name service with a base domain and registration fee."""
        if not domain:
            raise InvalidDomain('Domain cannot be empty.')
        if base_fee <= 0:
            raise InvalidFee('Fee must be a positive value.')

        self.domain = domain
        self.base_fee = base_fee
        self.total_fee = 0
        self.dev_address = ctx.caller_id
        
        self.fee_multiplier: dict[int, int] = {
            3: 20,
            4: 10,
            5: 1
        }

        self.max_profile_data_entries = max_profile_data_entries
        self.max_profile_key_length = max_profile_key_length
        self.max_profile_value_length = max_profile_value_length
        self.max_token_symbol_length = max_token_symbol_length
        self.max_total_profile_size = max_total_profile_size
        self.grace_period_days = grace_period_days
        self.max_managed_names = max_managed_names
        self.contract_version = "1.0.0"

        self.registered_names: dict[str, NameRecord]  = {}
        self.name_profile_data: dict[str, dict[str, str]] = {}
        self.name_profile_keys: dict[str, list[str]] = {}
        self.manager_names: dict[Address, list[str]]  = {}
        self.manager_primary_name: dict[Address, str] = {}

    @public(allow_deposit=True, allow_withdrawal=False)
    def create_name(self, ctx: Context, name: str, token_symbol: str) -> None:
        """Register a new name under the domain by minting an NFT."""
        if not self.validate_name(name):
            raise InvalidNameFormat

        if self.registered_names.get(name) is not None:
            # Name exists, check if it can be re-registered
            if self.is_name_available(name, ctx.block.timestamp):
                # It's expired and past grace period, so clean up before re-registering
                old_record = self.registered_names[name]
                self._remove_name_from_manager(old_record.manager_address, name)
            else:
                # It's not available (active or in grace period)
                record = self.registered_names[name]
                if record.expiration_date > ctx.block.timestamp:
                    raise NameAlreadyExists('Name is already registered')
                else:
                    grace_period_end = record.expiration_date + self.grace_period_days * SECONDS_PER_DAY
                    raise NameInGracePeriod(f'Name is in grace period until {grace_period_end}')

        if not (0 < len(token_symbol) <= self.max_token_symbol_length):
            raise InvalidTokenSymbol(f'Token symbol must be between 1 and {self.max_token_symbol_length} characters')

        # Verify fee payment
        fee = self.calculate_fee(name)
        years_of_access = self._get_years_of_access(ctx, fee)

        # Calculate expiration date
        expiration_date = ctx.block.timestamp + years_of_access * SECONDS_PER_YEAR

        # Mint new NFT and create name record
        token_uid = self._mint_name_nft(name, token_symbol, ctx.block.timestamp)
        
        self.registered_names.update({name: NameRecord(
            token_uid=token_uid,
            owner_address=ctx.caller_id, 
            is_deposited=True,
            manager_address=ctx.caller_id,
            resolving_address=ctx.caller_id,
            expiration_date=expiration_date
        )})
        
        # Initialize profile data for this name
        self.name_profile_data.update({name: {}})
        self.name_profile_keys.update({name: []})
        
        # Add to manager's list of names
        self._add_name_to_manager(ctx.caller_id, name)

        if self._check_manager_has_only_one_name(ctx.caller_id):
            self._set_manager_primary_name(ctx.caller_id, name)

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
        if self.registered_names.get(name) is None:   
            raise NameNotFound
            
        record = self.registered_names[name]
        
        # Get profile data for this name
        profile_data = self.name_profile_data.get(name, {})
        
        # Check if key exists
        if profile_data.get(key) is None:
            raise InvalidDataKey('Key does not exist in profile data')
            
        # Authorization check
        if record.manager_address != ctx.caller_id:
            raise NotAuthorized('Only the manager can delete profile data')
        
        # Remove the key from profile data
        del profile_data[key]
        self.name_profile_data.update({name: profile_data})
        
        # Remove key from keys list
        keys = list(self.name_profile_keys.get(name, []))
        if key in keys:
            keys.remove(key)
            self._update_profile_keys(name, keys)
    
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
        if self.registered_names.get(name) is None:
            raise NameNotFound

        # Validate key format and total size
        self.validate_key_format(key, value)
        
        record = self.registered_names[name]
        
        # Get profile data for this name
        profile_data = self.name_profile_data.get(name, {})
        
        # Validate total number of keys
        if len(profile_data) >= self.max_profile_data_entries and profile_data.get(key) is None:
            raise TooManyDataKeys(f'Maximum of {self.max_profile_data_entries} profile data keys allowed')
        
        # Authorization check
        if record.manager_address != ctx.caller_id:
            raise NotAuthorized('Only the manager can update profile data')

        # Update profile data
        is_new_key = profile_data.get(key) is None
        profile_data[key] = value
        self.name_profile_data.update({name: profile_data})
        
        # Add key to keys list if new
        if is_new_key:
            keys = list(self.name_profile_keys.get(name, []))
            keys.append(key)
            self._update_profile_keys(name, keys)

    @public(allow_actions=False)
    def change_name_owner(self, ctx: Context, name: str, new_owner_address: Address) -> None:
        """Change the owner address of a name."""
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]

        if not record.is_deposited:
            raise OwnershipNotReliable('The token must be deposited to change owner')

        if record.owner_address != ctx.caller_id:
            raise NotAuthorized('Only the current owner can change the owner address')

        self.registered_names.update({name: record.update_owner_address(new_owner_address)})

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
        if self.registered_names.get(name) is None:
            raise NameNotFound
        record = self.registered_names[name]
        
        # Check authorization
        is_owner = record.owner_address == ctx.caller_id and record.is_deposited
        is_manager = record.manager_address == ctx.caller_id
        
        if not (is_owner or is_manager):
            raise NotAuthorized('Only the owner or current manager can change the manager address')
            
        # If caller is owner, verify NFT is deposited
        if is_owner and not record.is_deposited:
            raise OwnershipNotReliable('The token must be deposited to change manager as owner')
            
        # Update manager mappings
        self._update_name_manager(name, record.manager_address, new_manager_address)
            
        self.registered_names.update({name: record.update_manager_address(new_manager_address)})

    @public(allow_actions=False)
    def change_manager_primary_name(self, ctx: Context, name: str) -> None:
        """Change the primary name for a manager."""
        if self.registered_names.get(name) is None:
            raise NameNotFound
        record = self.registered_names[name]
        if record.manager_address != ctx.caller_id:
            raise NotAuthorized('Only the manager can change the primary name')
        self._set_manager_primary_name(ctx.caller_id, name)

    @public(allow_actions=False)
    def change_resolving_address(self,
                                 ctx: Context,
                                 name: str,
                                 new_resolving_address: Address) -> None:
        """Change the resolving address of a name when authorized.
        
        Only the manager can change the resolving address.
        """
        if self.registered_names.get(name) is None:
            raise NameNotFound  
        record = self.registered_names[name]
        if record.manager_address != ctx.caller_id:
            raise NotAuthorized('Only the manager can change the resolving address')

        self.registered_names[name] = record.update_resolving_address(new_resolving_address)

    @public(allow_deposit=True, allow_withdrawal=False)
    def deposit_nft(self, ctx: Context, name: str) -> None:
        """Deposit NFT to enable name management."""
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]
        self._check_action_record_token(ctx, record.token_uid, NCActionType.DEPOSIT)
        if record.is_deposited:
            raise AlreadyDeposited('The token is already deposited')

        self.registered_names.update({name: record.toggle_is_deposited().update_owner_address(new_owner_address=ctx.caller_id)})

    @public(allow_deposit=False, allow_withdrawal=True)
    def withdraw_nft(self, ctx: Context, name: str) -> None:
        """Withdraw NFT to enable transfer."""
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]

        # Verify deposit ownership
        if record.owner_address != ctx.caller_id:
            raise NotAuthorized('You are not the owner of the token.')
        if not record.is_deposited:
            raise NotDeposited('The token is not deposited')
        self._check_action_record_token(ctx, record.token_uid, NCActionType.WITHDRAWAL)

        # Return NFT and revoke authorization
        self.registered_names.update({name: record.toggle_is_deposited()})

    @public(allow_deposit=True, allow_withdrawal=False)
    def renew_name(self, ctx: Context, name: str) -> None:
        """Renew a name registration for another period."""
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]

        # Verify fee payment
        fee = self.calculate_fee(name)
        years_of_access = self._get_years_of_access(ctx, fee)

        # Calculate new expiration date
        current_expiration = record.expiration_date
        new_expiration_date = max(current_expiration, ctx.block.timestamp) + years_of_access * SECONDS_PER_YEAR

        # Update expiration in record
        self.registered_names.update({name: record.update_expiration_date(new_expiration_date)})

        self.total_fee += fee * years_of_access

    @public(allow_actions=False)
    def change_fee(self, ctx: Context, new_fee: Amount) -> None:
        """Change the fee."""
        self._only_dev(ctx)
        if new_fee <= 0:
            raise InvalidFee('Fee must be a positive value.')
        self.base_fee = new_fee

    @public(allow_actions=False)
    def change_dev_address(self, ctx: Context, new_dev_address: Address) -> None:
        """Change the dev address."""
        self._only_dev(ctx)
        self.dev_address = new_dev_address

    @public(allow_actions=False)
    def change_fee_multiplier(self, ctx: Context, length: int, new_multiplier: int) -> None:
        """
            Change the fee multiplier.

            The possible lengths are: 3, 4, 5. 
            The multiplier of length 5 will be used for all other lengths.
        """
        self._only_dev(ctx)
        if self.fee_multiplier.get(length) is None:
            raise InvalidLength('Length not found in fee multiplier. Must be 3, 4 or 5. \
                                Length 5 will be used for all other lengths.')
        if new_multiplier <= 0:
            raise InvalidMultiplier('Multiplier must be a positive value.')
        self.fee_multiplier.update({length: new_multiplier})

    @public(allow_actions=False)
    def change_max_profile_data_entries(self, ctx: Context, new_max_profile_data_entries: int) -> None:
        """Change the maximum number of profile data entries."""
        self._only_dev(ctx)
        if new_max_profile_data_entries <= 0:
            raise InvalidMaxProfileDataEntries('Maximum number of profile data entries must be a positive value.')
        self.max_profile_data_entries = new_max_profile_data_entries

    @public(allow_actions=False)
    def change_max_profile_key_length(self, ctx: Context, new_max_profile_key_length: int) -> None:
        """Change the maximum length of profile data keys."""
        self._only_dev(ctx)
        if new_max_profile_key_length <= 0:
            raise InvalidMaxProfileKeyLength('Maximum length of profile data keys must be a positive value.')
        self.max_profile_key_length = new_max_profile_key_length

    @public(allow_actions=False)
    def change_max_profile_value_length(self, ctx: Context, new_max_profile_value_length: int) -> None:
        """Change the maximum length of profile data values."""
        self._only_dev(ctx)
        if new_max_profile_value_length <= 0:
            raise InvalidMaxProfileValueLength('Maximum length of profile data values must be a positive value.')
        self.max_profile_value_length = new_max_profile_value_length

    @public(allow_actions=False)
    def change_max_token_symbol_length(self, ctx: Context, new_max_token_symbol_length: int) -> None:
        """Change the maximum length of token symbols."""
        self._only_dev(ctx)
        if new_max_token_symbol_length <= 0:
            raise InvalidMaxTokenSymbolLength('Maximum length of token symbols must be a positive value.')
        self.max_token_symbol_length = new_max_token_symbol_length

    @public(allow_actions=False)
    def change_max_total_profile_size(self, ctx: Context, new_max_total_profile_size: int) -> None:
        """Change the maximum total size of all profile data."""
        self._only_dev(ctx)
        if new_max_total_profile_size <= 0:
            raise InvalidMaxTotalProfileSize('Maximum total size of all profile data must be a positive value.')
        self.max_total_profile_size = new_max_total_profile_size

    @public(allow_actions=False)
    def change_grace_period_days(self, ctx: Context, new_grace_period_days: int) -> None:
        """Change the grace period days."""
        self._only_dev(ctx)
        if new_grace_period_days <= 0:
            raise InvalidGracePeriodDays('Grace period days must be a positive value.')
        self.grace_period_days = new_grace_period_days

    @public(allow_actions=False)
    def change_max_managed_names(self, ctx: Context, new_max_managed_names: int) -> None:
        """Change the maximum number of names a single address can manage.
        
        The limit can only be increased, never decreased. This prevents existing
        managers from being locked out of their names if the limit is changed.
        
        Args:
            ctx: Transaction context
            new_max_managed_names: New maximum limit (must be higher than current)
            
        Raises:
            InvalidMaxManagedNames: If new limit is not positive
            CannotDecreaseLimit: If new limit is lower than current limit
        """
        self._only_dev(ctx)
        if new_max_managed_names <= 0:
            raise InvalidMaxManagedNames('Maximum number of managed names must be a positive value.')
        if new_max_managed_names < self.max_managed_names:
            raise CannotDecreaseLimit(f'Cannot decrease limit from {self.max_managed_names} to {new_max_managed_names}. The limit can only be increased.')
        self.max_managed_names = new_max_managed_names

    @public
    def upgrade_contract(self, ctx: Context, new_blueprint_id: BlueprintId, new_version: str) -> None:
        """Upgrade the contract to a new blueprint version.

        Args:
            ctx: Transaction context
            new_blueprint_id: The blueprint ID to upgrade to
            new_version: Version string for the new blueprint (e.g., "1.1.0")

        Raises:
            Unauthorized: If caller is not the owner
            InvalidVersion: If new version is not higher than current version
        """
        # Only owner can upgrade
        self._only_dev(ctx)

        # Validate version is newer
        if not self._is_version_higher(new_version, self.contract_version):
            raise InvalidVersion(f"New version {new_version} must be higher than current {self.contract_version}")
        self.contract_version = new_version
        
        # Perform the upgrade
        self.syscall.change_blueprint(new_blueprint_id)

    @view
    def is_name_available(self, name: str, now_timestamp: Timestamp) -> bool:
        """Check if a name is available for registration.
        
        A name is available if:
        1. It doesn't exist in the registry, or
        2. It's expired AND past the grace period
        
        Args:
            name: The name to check
            now_timestamp: The current timestamp to check against
        """
        if self.registered_names.get(name) is None:
            return True
            
        record = self.registered_names[name]
        expiration_date = record.expiration_date
        grace_period_end = expiration_date + self.grace_period_days * SECONDS_PER_DAY
        
        return now_timestamp > grace_period_end

    @view
    def resolve_name(self, name: str, now_timestamp: Timestamp) -> str:
        """Get the resolving address associated with a name."""
        self._check_name_expired(name, now_timestamp)
        resolving_address = self.registered_names[name].resolving_address
        return str(resolving_address)

    @view
    def get_name_data(self, name: str) -> dict[str, str]:
        """Get NameRecord data associated with a name in a JSON-serializable format.
        
        Note: Profile data is not included. Use get_profile_data to retrieve profile data.
        """
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]
        return self._serialize_name_record(name, record)
    
    @view
    def get_profile_data(self, name: str) -> dict[str, str]:
        """Get all profile data for a name.
        
        Args:
            name: The registered name
            
        Returns:
            A dict containing all profile key-value pairs for this name
            
        Raises:
            NameNotFound: If the name is not registered
        """
        if self.registered_names.get(name) is None:
            raise NameNotFound
        
        result: dict[str, str] = {}
        profile_keys = self.name_profile_keys.get(name, [])
        profile_data = self.name_profile_data.get(name, {})
        
        for key in profile_keys:
            value = profile_data.get(key)
            if value is not None:
                result.update({key: value})
                
        return result

    @view
    def get_name_owner(self, name: str) -> str:
        """Get the name owner's address."""
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]
        if not record.is_deposited:
            raise OwnershipNotReliable('The token is not deposited \
                on the contract, we can\'t say for sure who is \
                the owner at this moment.')

        return str(record.owner_address)

    @view
    def get_name_expiration_info(self, name: str, now_timestamp: Timestamp) -> dict[str, str]:
        """Get detailed expiration information for a name.
        
        Args:
            name: The name to check
            now_timestamp: The current timestamp to check against
            
        Returns a dictionary containing:
        - expiration_date: The expiration date in seconds (timestamp)
        - grace_period_end: The grace period end date in seconds (timestamp)
        - status: Current status (active, grace_period, or available)
        """
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]
        expiration_date = record.expiration_date
        grace_period_end = expiration_date + self.grace_period_days * SECONDS_PER_DAY
        today = now_timestamp
        
        if today < expiration_date:
            status = 'active'
        elif today < grace_period_end:
            status = 'grace_period'
        else:
            status = 'available'
            
        return {
            'expiration_date': str(expiration_date),
            'grace_period_end': str(grace_period_end),
            'status': status,
        }
        
    @view
    def get_name_expiration_date(self, name: str) -> Timestamp:
        """Get the expiration date of a name registration."""
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]
        return record.expiration_date

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
        if not isinstance(key, str) or not key or len(key) > self.max_profile_key_length:
            raise InvalidDataKey(f'Key must be between 1 and {self.max_profile_key_length} characters')
        
        # Only allow alphanumeric and underscores in keys
        if not key.replace('_', '').isalnum():
            raise InvalidDataKey('Key must contain only letters, numbers, and underscores')
        
        # Validate value
        if not isinstance(value, str) or not value or len(value) > self.max_profile_value_length:
            raise InvalidDataValue(f'Value must be between 1 and {self.max_profile_value_length} characters')
            
        # Check for control characters in value (allow newline, tab, carriage return)
        if value.find('\x00') >= 0:  # Null byte
            raise InvalidDataValue('Value contains invalid control characters')
            
        return True

    @view
    def get_dev_address(self) -> str:
        """Get the developer's address."""
        return str(self.dev_address)

    @view
    def get_contract_domain(self) -> str:
        """Get the contract domain."""
        return self.domain
        
    @view
    def check_name_ownership(self, name: str, address: Address, now_timestamp: Timestamp) -> bool:
        """Check if a specific name is owned by an address.
        
        Args:
            name: The name to check
            address: The address to verify ownership for
            now_timestamp: The current timestamp to check against
            
        Returns:
            bool: True if the address owns the name, False otherwise
        """
        if self.registered_names.get(name) is None:
            return False
            
        record = self.registered_names[name]
        if record.owner_address != address:
            return False
            
        # Check if expired
        expiration_date = record.expiration_date
        if expiration_date < now_timestamp:
            return False
            
        return True
        
    @view
    def check_name_status(self, name: str, now_timestamp: Timestamp) -> str:
        """Check the status of a specific name.
        
        Args:
            name: The name to check
            now_timestamp: The current timestamp to check against
            
        Returns:
            str: 'active', 'expired', or 'available'
        """
        if self.registered_names.get(name) is None:
            return 'available'
            
        record = self.registered_names[name]
        expiration_date = record.expiration_date
        
        if expiration_date < now_timestamp:
            grace_period_end = expiration_date + self.grace_period_days * SECONDS_PER_DAY
            if now_timestamp > grace_period_end:
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
        if self.fee_multiplier.get(length) is not None:
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
        if length > 5:
            length = 5
        elif length < 3:
            raise InvalidLength('Length must be at least 3 characters.')
        return self.fee_multiplier.get(length, 1)
        
    @view
    def get_manager_names(self, manager_address: Address) -> list[str]:
        """Get all names managed by a specific address.
        
        Args:
            manager_address: The address to check
            
        Returns:
            list[str]: List of names managed by this address
        """
        return list(self.manager_names.get(manager_address, []))
    
    @view
    def get_manager_primary_name(self, manager_address: Address) -> str:
        """Get the primary name for a manager."""
        return self.manager_primary_name.get(manager_address, '')
        
    @view
    def get_fee_structure(self) -> dict[str, int]:
        """Get the complete fee structure information.
        
        Returns a dictionary containing:
        - base_fee: The base registration fee
        - multipliers: Dictionary of length-to-multiplier mappings
        - default_multiplier: The multiplier used for lengths > 5
        """
        return {
            'base_fee': self.base_fee,
            'three_length_multiplier': self.fee_multiplier[3],
            'four_length_multiplier': self.fee_multiplier[4],
            'five_plus_length_multiplier': self.fee_multiplier[5],
            'default_multiplier': self.fee_multiplier[5]
        }

    @view
    def get_max_profile_data_entries(self) -> int:
        """Get the maximum number of profile data entries."""
        return self.max_profile_data_entries

    @view
    def get_max_profile_key_length(self) -> int:
        """Get the maximum length of profile data keys."""
        return self.max_profile_key_length

    @view
    def get_max_profile_value_length(self) -> int:
        """Get the maximum length of profile data values."""
        return self.max_profile_value_length

    @view
    def get_max_token_symbol_length(self) -> int:
        """Get the maximum length of token symbols."""
        return self.max_token_symbol_length

    @view
    def get_max_total_profile_size(self) -> int:
        """Get the maximum total size of all profile data."""
        return self.max_total_profile_size

    @view
    def get_grace_period_days(self) -> int:
        """Get the grace period days."""
        return self.grace_period_days

    @view
    def get_contract_version(self) -> str:
        """Get the current contract version.

        Returns:
            Version string (e.g., "1.0.0")
        """
        return self.contract_version

    @view
    def get_max_managed_names(self) -> int:
        """Get the maximum number of names a single address can manage.

        Returns:
            Maximum number of managed names allowed per address
        """
        return self.max_managed_names

    def _only_dev(self, ctx: Context) -> None:
        """Check if the caller is the developer."""
        if ctx.caller_id != self.dev_address:
            raise NotAuthorized

    def _mint_name_nft(self, name: str, token_symbol: str, timestamp: Timestamp) -> TokenUid:
        """Mint a new NFT for the name and return its UID."""
        # Create NFT metadata
        nft_name = f'{name[:26]}.{self.domain}'
        
        token_uid = self.syscall.create_deposit_token(
            token_name=nft_name, 
            token_symbol=token_symbol,
            amount=1,
            melt_authority=True,
            mint_authority=True,
            salt=bytes(timestamp)
        )
        
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
        if self.registered_names.get(name) is None:
            raise NameNotFound

        return self.registered_names[name].owner_address

    def _get_action(self, ctx: Context) -> NCAction:
        """Return the only action available; fails otherwise."""
        if len(ctx.actions) != 1:
            raise TooManyActions('Only one action supported.')
        action = next(iter(ctx.actions.values()))[0]
        if ctx.caller_id != self.dev_address and action.type == NCActionType.WITHDRAWAL:
            raise WithdrawalNotAllowed('Only dev can withdraw.')
        if action.token_uid != HATHOR_TOKEN_UID:
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

    def _get_years_of_access(self, ctx: Context, fee: Amount):
        """Return the number of years that have been bought."""
        action = self._get_action(ctx)
        if action.amount < fee:
            raise InsufficientBalance(f'Deposit amount is less than fee ({fee}).')
        if action.amount % fee != 0:
            raise InvalidAmount(f'Deposit amount must be a multiple of the fee ({fee}).')

        return action.amount // fee

    def _check_name_expired(self, name: str, now_timestamp: Timestamp) -> bool:
        """Check if a name registration has expired.
        
        Args:
            name: The name to check
            now_timestamp: The current timestamp to check against
        """
        if self.registered_names.get(name) is None:
            raise NameNotFound

        record = self.registered_names[name]
        expiration_date = record.expiration_date
        if expiration_date < now_timestamp:
            raise NameExpired('Name registration has expired')
    
    def _add_name_to_manager(self, manager_address: Address, name: str) -> None:
        """Add a name to a manager's list of managed names.
        
        Raises:
            MaxManagedNamesExceeded: If the manager already has MAX_MANAGED_NAMES names
        """
        if self.manager_names.get(manager_address) is None:
            self.manager_names[manager_address] = []
        names = self.manager_names[manager_address]
        
        # Check if manager has reached the limit before adding a new name
        if name not in names and len(names) >= self.max_managed_names:
            raise MaxManagedNamesExceeded(f'Manager address has reached the maximum limit of {self.max_managed_names} managed names')
        
        if name not in names:
            names.append(name)
            
    def _remove_name_from_manager(self, manager_address: Address, name: str) -> None:
        """Remove a name from a manager's list of managed names."""
        if self.manager_names.get(manager_address) is not None:
            names = list(self.manager_names[manager_address])
            if name in names:
                names.remove(name)
                for _ in range(len(names)+1):
                    self.manager_names[manager_address].pop()
                del self.manager_names[manager_address]
                self.manager_names.update({manager_address: names})

            if not names:
                del self.manager_names[manager_address]
                del self.manager_primary_name[manager_address]
            else:
                # If the removed name was the primary, set a new primary.
                if self.manager_primary_name.get(manager_address) == name:
                    self._set_manager_primary_name(manager_address, '')

    def _update_name_manager(self, name: str, old_manager: Address, new_manager: Address) -> None:
        """Update manager mappings when a name's manager changes."""
        self._remove_name_from_manager(old_manager, name)
        self._add_name_to_manager(new_manager, name)
    
    def _update_profile_keys(self, name: str, new_keys: list[str]) -> None:
        """Update the profile keys list for a name.
        
        This clears the existing list and adds the new keys.
        """
        existing = self.name_profile_keys.get(name)
        if existing is not None:
            num_items = len(existing)
            for _ in range(num_items):
                existing.pop()
            for key in new_keys:
                existing.append(key)
        else:
            self.name_profile_keys.update({name: new_keys})
    
    def _serialize_name_record(self, name: str, record: NameRecord) -> dict[str, str]:
        """Serialize NameRecord to a JSON-serializable dict.
        
        Note: Profile data is not included. Use get_profile_data to retrieve profile data.
        """
        return {
            'token_uid': record.token_uid.hex(),
            'owner_address': str(record.owner_address),
            'is_deposited': str(record.is_deposited),
            'manager_address': str(record.manager_address),
            'resolving_address': str(record.resolving_address),
            'expiration_date': str(record.expiration_date)
        }

    def _check_manager_has_only_one_name(self, manager_address: Address) -> bool:
        """Check if a manager has any names."""
        if self.manager_names.get(manager_address) is None:
            return False
        return len(self.manager_names[manager_address]) == 1

    def _set_manager_primary_name(self, manager_address: Address, name: str) -> None:
        """Set the primary name for a manager."""
        if name:
            self.manager_primary_name.update({manager_address: name})
        elif self.manager_primary_name.get(manager_address) is not None:
            del self.manager_primary_name[manager_address]

    def _is_version_higher(self, new_version: str, current_version: str) -> bool:
        """Compare semantic versions (e.g., "1.2.3").

        Returns True if new_version > current_version.
        Returns False if versions are malformed or equal.
        """
        # Split versions by '.'
        new_parts_str = new_version.split('.')
        current_parts_str = current_version.split('.')
        
        # Check if all parts are valid integers
        new_parts: list[int] = []
        for part in new_parts_str:
            # Simple check: all characters must be digits
            if not part or not all(c in '0123456789' for c in part):
                return False  # Invalid format
            new_parts.append(int(part))
        
        current_parts: list[int] = []
        for part in current_parts_str:
            if not part or not all(c in '0123456789' for c in part):
                return False  # Invalid format
            current_parts.append(int(part))

        # Pad shorter version with zeros
        max_len = len(new_parts) if len(new_parts) > len(current_parts) else len(current_parts)
        while len(new_parts) < max_len:
            new_parts.append(0)
        while len(current_parts) < max_len:
            current_parts.append(0)

        # Compare versions
        return new_parts > current_parts

    

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

class InvalidMaxProfileDataEntries(NCFail):
    """Raised when an invalid maximum number of profile data entries is provided."""
    pass

class InvalidMaxProfileKeyLength(NCFail):
    """Raised when an invalid maximum length of profile data keys is provided."""
    pass

class InvalidMaxProfileValueLength(NCFail):
    """Raised when an invalid maximum length of profile data values is provided."""
    pass

class InvalidMaxTokenSymbolLength(NCFail):
    """Raised when an invalid maximum length of token symbols is provided."""
    pass

class InvalidMaxTotalProfileSize(NCFail):
    """Raised when an invalid maximum total size of all profile data is provided."""
    pass

class InvalidGracePeriodDays(NCFail):
    """Raised when an invalid grace period days is provided."""
    pass

class AlreadyDeposited(NCFail):
    """Raised when attempting to deposit a token that is already deposited."""
    pass

class NotDeposited(NCFail):
    """Raised when attempting to perform an operation on a token that is not deposited."""
    pass

class InvalidVersion(NCFail):
    """Raised when an invalid version is provided."""
    pass

class MaxManagedNamesExceeded(NCFail):
    """Raised when attempting to add a name to a manager that has reached the maximum limit.
    
    Each address can manage up to max_managed_names names. This prevents
    excessive resource usage and ensures fair distribution of names.
    """
    pass

class InvalidMaxManagedNames(NCFail):
    """Raised when an invalid maximum number of managed names is provided."""
    pass

class CannotDecreaseLimit(NCFail):
    """Raised when attempting to decrease the max_managed_names limit.
    
    The limit can only be increased to prevent existing managers from being
    locked out of their names.
    """
    pass