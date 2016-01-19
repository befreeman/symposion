import datetime
import pytz

from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from symposion.registration import models as rego
from symposion.registration.cart import CartController

from patch_datetime import SetTimeMixin

UTC = pytz.timezone('UTC')

class AddToCartTestCase(SetTimeMixin, TestCase):

    def setUp(self):
        super(AddToCartTestCase, self).setUp()

    @classmethod
    def setUpTestData(cls):
        cls.USER_1 = User.objects.create_user(username='testuser',
            email='test@example.com', password='top_secret')

        cls.USER_2 = User.objects.create_user(username='testuser2',
            email='test2@example.com', password='top_secret')

        cls.CAT_1 = rego.Category.objects.create(
            name="Category 1",
            description="This is a test category",
            order=10,
            render_type=rego.Category.RENDER_TYPE_RADIO,
        )
        cls.CAT_1.save()

        cls.RESERVATION = datetime.timedelta(hours=1)

        cls.PROD_1 = rego.Product.objects.create(
            name="Product 1",
            description= "This is a test product. It costs $10. " \
                "A user may have 10 of them.",
            category=cls.CAT_1,
            price=Decimal("10.00"),
            reservation_duration=cls.RESERVATION,
            limit_per_user=10,
            order=10,
        )
        cls.PROD_1.save()

        cls.PROD_2 = rego.Product.objects.create(
            name="Product 2",
            description= "This is a test product. It costs $10. " \
                "A user may have 10 of them.",
            category=cls.CAT_1,
            price=Decimal("10.00"),
            limit_per_user=10,
            order=10,
        )
        cls.PROD_2.save()

    def test_get_cart(self):
        current_cart = CartController(self.USER_1)

        current_cart.cart.active = False
        current_cart.cart.save()

        old_cart = current_cart

        current_cart = CartController(self.USER_1)
        self.assertNotEqual(old_cart.cart, current_cart.cart)

        current_cart2 = CartController(self.USER_1)
        self.assertEqual(current_cart.cart, current_cart2.cart)


    def test_add_to_cart_collapses_product_items(self):
        current_cart = CartController(self.USER_1)

        # Add a product twice
        current_cart.add_to_cart(self.PROD_1, 1)
        current_cart.add_to_cart(self.PROD_1, 1)

        ## Count of products for a given user should be collapsed.
        items = rego.ProductItem.objects.filter(cart=current_cart.cart,
            product=self.PROD_1)
        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEquals(2, item.quantity)


    def test_add_to_cart_per_user_limit(self):
        current_cart = CartController(self.USER_1)

        # User should be able to add 1 of PROD_1 to the current cart.
        current_cart.add_to_cart(self.PROD_1, 1)

        # User should be able to add 1 of PROD_1 to the current cart.
        current_cart.add_to_cart(self.PROD_1, 1)

        # User should not be able to add 10 of PROD_1 to the current cart now,
        # because they have a limit of 10.
        with self.assertRaises(ValidationError):
            current_cart.add_to_cart(self.PROD_1, 10)

        current_cart.cart.active = False
        current_cart.cart.save()

        current_cart = CartController(self.USER_1)
        # User should not be able to add 10 of PROD_1 to the current cart now,
        # even though it's a new cart.
        with self.assertRaises(ValidationError):
            current_cart.add_to_cart(self.PROD_1, 10)

        # Second user should not be affected by first user's limits
        second_user_cart = CartController(self.USER_2)
        second_user_cart.add_to_cart(self.PROD_1, 10)


    def test_add_to_cart_ceiling_limit(self):
        limit_ceiling = rego.TimeOrStockLimitEnablingCondition.objects.create(
            description="Limit ceiling",
            mandatory=True,
            limit=9,
        )
        limit_ceiling.save()
        limit_ceiling.products.add(self.PROD_1, self.PROD_2)
        limit_ceiling.save()

        current_cart = CartController(self.USER_1)

        # User should not be able to add 10 of PROD_1 to the current cart
        # because it is affected by limit_ceiling
        with self.assertRaises(ValidationError):
            current_cart.add_to_cart(self.PROD_2, 10)

        # User should be able to add 5 of PROD_1 to the current cart
        current_cart.add_to_cart(self.PROD_1, 5)

        # User should not be able to add 10 of PROD_2 to the current cart
        # because it is affected by CEIL_1
        with self.assertRaises(ValidationError):
            current_cart.add_to_cart(self.PROD_2, 10)

        # User should be able to add 5 of PROD_2 to the current cart
        current_cart.add_to_cart(self.PROD_2, 4)

    def test_add_to_cart_ceiling_date_range(self):
        date_range_ceiling = rego.TimeOrStockLimitEnablingCondition.objects.create(
            description="Date range ceiling",
            mandatory=True,
            start_time=datetime.datetime(2015, 01, 01, tzinfo=UTC),
            end_time=datetime.datetime(2015, 02, 01, tzinfo=UTC),
        )
        date_range_ceiling.save()
        date_range_ceiling.products.add(self.PROD_1)
        date_range_ceiling.save()

        current_cart = CartController(self.USER_1)

        # User should not be able to add whilst we're before start_time
        self.set_time(datetime.datetime(2014, 01, 01, tzinfo=UTC))
        with self.assertRaises(ValidationError):
            current_cart.add_to_cart(self.PROD_1, 1)

        # User should be able to add whilst we're during date range
        # On edge of start
        self.set_time(datetime.datetime(2015, 01, 01, tzinfo=UTC))
        current_cart.add_to_cart(self.PROD_1, 1)
        # In middle
        self.set_time(datetime.datetime(2015, 01, 15, tzinfo=UTC))
        current_cart.add_to_cart(self.PROD_1, 1)
        # On edge of end
        self.set_time(datetime.datetime(2015, 02, 01, tzinfo=UTC))
        current_cart.add_to_cart(self.PROD_1, 1)

        # User should not be able to add whilst we're after date range
        self.set_time(datetime.datetime(2014, 01, 01, minute=01, tzinfo=UTC))
        with self.assertRaises(ValidationError):
            current_cart.add_to_cart(self.PROD_1, 1)


    def test_add_to_cart_ceiling_limit_reserved_carts(self):
        limit_ceiling = rego.TimeOrStockLimitEnablingCondition.objects.create(
            description="Limit ceiling",
            mandatory=True,
            limit=1,
        )
        limit_ceiling.save()
        limit_ceiling.products.add(self.PROD_1)
        limit_ceiling.save()

        self.set_time(datetime.datetime(2015, 01, 01, tzinfo=UTC))

        first_cart = CartController(self.USER_1)
        second_cart = CartController(self.USER_2)

        first_cart.add_to_cart(self.PROD_1, 1)

        # User 2 should not be able to add item to their cart
        # because user 1 has item reserved, exhausting the ceiling
        with self.assertRaises(ValidationError):
            second_cart.add_to_cart(self.PROD_1, 1)

        # User 2 should be able to add item to their cart once the
        # reservation duration is elapsed
        self.add_timedelta(self.RESERVATION + datetime.timedelta(seconds=1))
        second_cart.add_to_cart(self.PROD_1, 1)

        # User 2 pays for their cart
        second_cart.cart.active = False
        second_cart.cart.save()

        # User 1 should not be able to add item to their cart
        # because user 2 has paid for their reserved item, exhausting
        # the ceiling, regardless of the reservation time.
        self.add_timedelta(self.RESERVATION * 20)
        with self.assertRaises(ValidationError):
            first_cart.add_to_cart(self.PROD_1, 1)
